"""模组更新检测：读 manifest.json 里的 UpdateKeys，去 Nexus / GitHub 查最新版本。

支持的键格式（SMAPI 规范）：
    Nexus:1915
    GitHub:Pathoschild/SMAPI
    GitHub:owner/repo@branch
    ModDrop:12345        （暂不支持查询）
    CurseForge:123456    （暂不支持查询）
    Chucklefish:...      （暂不支持查询）

Nexus 需要用户自己的 API Key（Nexus 账号设置里免费申请），
GitHub 匿名接口有每小时 60 次的限制，正常情况下够用。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

NEXUS_GAME = "stardewvalley"
CACHE_TTL = 12 * 3600  # 同一版本 12 小时内不重复查询
SUPPORTED = ("nexus", "github")


class UpdateError(RuntimeError):
    pass


def _http_json(url: str, headers: dict | None = None, timeout: int = 25):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "StardewModManager/1.0",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:160]
        raise UpdateError(f"HTTP {exc.code} {body}") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(str(exc)) from exc


def parse_keys(keys) -> list:
    """把 UpdateKeys 解析成 [(来源, 标识)]。"""
    out = []
    for raw in keys or []:
        text = str(raw).strip()
        if not text or ":" not in text:
            continue
        source, value = text.split(":", 1)
        source = source.strip().lower()
        value = value.strip()
        if not value:
            continue
        out.append((source, value))
    return out


def _clean(version: str) -> str:
    return re.sub(r"^[vV]", "", str(version or "").strip())


def _ver_tuple(text: str):
    return tuple(int(x) for x in re.findall(r"\d+", str(text or ""))[:4])


def _pad(a: tuple, b: tuple):
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def is_newer(latest: str, current: str) -> bool:
    """6.6 与 6.6.0 视为同一版本（补零比较，避免误报）。"""
    a, b = _ver_tuple(latest), _ver_tuple(current)
    if not a:
        return False
    if not b:
        return True
    a, b = _pad(a, b)
    return a > b


def github_latest(slug: str) -> dict:
    slug = slug.split("@")[0].strip().strip("/")
    if slug.lower().endswith(".git"):
        slug = slug[:-4]
    if slug.count("/") < 1:
        raise UpdateError(f"GitHub 标识不规范：{slug}")
    data = _http_json(f"https://api.github.com/repos/{slug}/releases/latest")
    tag = _clean(data.get("tag_name") or data.get("name") or "")
    return {
        "latest": tag,
        "url": data.get("html_url") or f"https://github.com/{slug}/releases",
        "title": data.get("name") or tag,
    }


def nexus_latest(mod_id: str, api_key: str) -> dict:
    """走官方 API（需要 Personal API Key）。"""
    if not api_key:
        raise UpdateError("没有配置 Nexus API Key")
    data = _http_json(
        f"https://api.nexusmods.com/v1/games/{NEXUS_GAME}/mods/{str(mod_id).strip()}.json",
        headers={"apikey": api_key},
    )
    version = _clean(data.get("version") or "")
    return {
        "latest": version,
        "url": f"https://www.nexusmods.com/{NEXUS_GAME}/mods/{mod_id}",
        "title": data.get("name") or "",
        "method": "api",
    }


# ---------------------------------------------------------------- Cookie 方式
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_VERSION_PATTERNS = (
    r'"version"\s*:\s*"([^"]{1,24})"',
    r'\\"version\\"\s*:\s*\\"([^\\"]{1,24})\\"',
    r'data-version="([^"]{1,24})"',
    r'class="[^"]*file-version[^"]*"[^>]*>\s*([^<]{1,24})<',
    r'itemprop="version"[^>]*>\s*([^<]{1,24})<',
)
_LABEL_PATTERNS = (
    r">\s*Version\s*<[^>]*>\s*<[^>]*>\s*([^<]{1,24})<",
    r">\s*Version\s*<[^>]*>\s*([^<]{1,24})<",
    r"Version[^0-9A-Za-z]{0,12}(v?\d+\.\d+(?:\.\d+){0,2})",
)


def fetch_page(url: str, cookie: str = "", timeout: int = 30) -> str:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.nexusmods.com/",
    }
    if cookie:
        headers["Cookie"] = cookie.strip()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise UpdateError(
                "被 Cloudflare 拦了（403）：说明 Cookie 无效或已过期，"
                "请重新从浏览器复制一次（要包含 cf_clearance 与 nexusmods_session）"
            ) from exc
        if exc.code == 404:
            raise UpdateError("页面不存在（404），可能该 Mod 已下架或链接变了") from exc
        raise UpdateError(f"HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(str(exc)) from exc


def parse_version_from_html(html: str) -> str:
    """从 Nexus 页面里尽量挖出版本号。"""
    if not html:
        return ""
    if "Just a moment" in html[:2000]:
        raise UpdateError("页面是 Cloudflare 验证页，Cookie 没过验证")
    for pattern in _VERSION_PATTERNS:
        found = re.findall(pattern, html, re.I)
        if found:
            for item in found:
                text = _clean(item)
                if _ver_tuple(text):
                    return text
    for pattern in _LABEL_PATTERNS:
        found = re.findall(pattern, html, re.I)
        if found:
            for item in found:
                text = _clean(item)
                if _ver_tuple(text):
                    return text
    return ""


def nexus_latest_page(mod_id: str, cookie: str) -> dict:
    """不带 API Key 时：带着浏览器 Cookie 抓公开页面。"""
    if not cookie:
        raise UpdateError("没有配置 Nexus Cookie")
    mid = str(mod_id).strip()
    url = f"https://www.nexusmods.com/{NEXUS_GAME}/mods/{mid}?tab=files"
    html = fetch_page(url, cookie)
    version = parse_version_from_html(html)
    if not version:
        raise UpdateError("页面抓到了，但没找到版本号（可能 N 网改版，请把 nexus_debug.html 发我）")
    title = ""
    m = re.search(r"<title>\s*(.*?)\s*(?:at|</title>)", html, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
    return {
        "latest": version,
        "url": f"https://www.nexusmods.com/{NEXUS_GAME}/mods/{mid}",
        "title": title,
        "method": "cookie",
    }


class NexusClient:
    """按「API Key 优先，其次 Cookie」的顺序查询。"""

    def __init__(self, api_key: str = "", cookie: str = ""):
        self.api_key = (api_key or "").strip()
        self.cookie = (cookie or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self.api_key or self.cookie)

    def how(self) -> str:
        if self.api_key:
            return "API Key"
        if self.cookie:
            return "Cookie"
        return "未配置"

    def latest(self, mod_id: str) -> dict:
        if self.api_key:
            return nexus_latest(mod_id, self.api_key)
        return nexus_latest_page(mod_id, self.cookie)


def nexus_self_test(client: NexusClient, mod_id: str = "1915") -> dict:
    """给设置页做连通性测试，返回详细信息。"""
    out = {"ok": False, "method": client.how(), "version": "", "error": "", "html": ""}
    if not client.ready:
        out["error"] = "既没有 API Key 也没有 Cookie"
        return out
    try:
        info = client.latest(mod_id)
        out.update(ok=bool(info.get("latest")), version=info.get("latest") or "",
                   title=info.get("title") or "", method=info.get("method") or client.how())
        if not out["ok"]:
            out["error"] = "能访问但没解析出版本号"
    except UpdateError as exc:
        out["error"] = str(exc)
        if "版本号" in str(exc) or "验证页" in str(exc):
            try:
                out["html"] = fetch_page(
                    f"https://www.nexusmods.com/{NEXUS_GAME}/mods/{mod_id}?tab=files", client.cookie
                )
            except Exception:  # noqa: BLE001
                pass
    return out


def check_mod(mod, nexus_key: str = "", nexus_cookie: str = "") -> dict:
    """查询单个模组。返回 {status, latest, url, source, note}。"""
    keys = parse_keys(getattr(mod, "update_keys", []) or [])
    if not keys:
        return {"status": "unknown", "note": "没有 UpdateKeys，无法自动检查", "latest": "", "url": ""}
    client = NexusClient(nexus_key, nexus_cookie)
    notes = []
    for source, value in keys:
        try:
            if source == "nexus":
                if not client.ready:
                    notes.append("Nexus 需要在设置里填 API Key 或 Cookie")
                    continue
                info = client.latest(value)
            elif source == "github":
                info = github_latest(value)
            else:
                notes.append(f"{source} 暂不支持查询")
                continue
        except UpdateError as exc:
            notes.append(f"{source}: {exc}")
            continue
        latest = info.get("latest") or ""
        status = "new" if is_newer(latest, mod.version) else "ok"
        return {
            "status": status,
            "latest": latest,
            "url": info.get("url") or "",
            "source": source,
            "method": info.get("method") or "",
            "note": "" if latest else "对方没有提供版本号",
        }
    if notes and all(("API Key" in n or "Cookie" in n or "不支持" in n) for n in notes):
        return {"status": "skip", "note": "；".join(notes), "latest": "", "url": ""}
    return {"status": "error", "note": "；".join(notes)[:200], "latest": "", "url": ""}


def check_all(mods: list, nexus_key: str = "", nexus_cookie: str = "", workers: int = 6,
              progress=None, should_stop=None, cache=None, ttl: int = CACHE_TTL) -> dict:
    """并发检查全部模组。12 小时内查过且版本没变的直接复用缓存（省时间、省额度）。"""
    result = {}
    todo = []
    for m in mods:
        if not getattr(m, "unique_id", ""):
            continue
        hit = cache.get(m.unique_id, m.version, ttl) if cache is not None else None
        if hit:
            result[m.unique_id] = dict(hit, name=m.name, current=m.version, cached=True)
        else:
            todo.append(m)
    total = len(todo)
    done = 0

    def work(mod):
        return mod.unique_id, check_mod(mod, nexus_key, nexus_cookie)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, m): m for m in todo}
        for fut in as_completed(futures):
            if should_stop and should_stop():
                break
            mod = futures[fut]
            try:
                uid, info = fut.result()
            except Exception as exc:  # noqa: BLE001
                uid, info = mod.unique_id, {"status": "error", "note": str(exc)[:160], "latest": "", "url": ""}
            info["name"] = mod.name
            info["current"] = mod.version
            info["checked"] = time.time()
            result[uid] = info
            done += 1
            if progress:
                progress(done, total, mod.name)
    return result


# ---------------------------------------------------------------- 缓存
class UpdateCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = raw
        except Exception:  # noqa: BLE001
            self.data = {}

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def get(self, unique_id: str, current_version: str, ttl: int = CACHE_TTL):
        item = self.data.get(unique_id)
        if not isinstance(item, dict):
            return None
        if str(item.get("current") or "") != str(current_version or ""):
            return None
        if time.time() - float(item.get("checked") or 0) > ttl:
            return None
        return item

    def put(self, unique_id: str, info: dict) -> None:
        self.data[unique_id] = {
            "status": info.get("status"),
            "latest": info.get("latest"),
            "url": info.get("url"),
            "source": info.get("source"),
            "note": info.get("note"),
            "current": info.get("current"),
            "checked": info.get("checked") or time.time(),
        }

    def clear(self) -> None:
        self.data = {}
        self.save()
