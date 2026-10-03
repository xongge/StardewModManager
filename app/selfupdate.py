"""软件自身的更新检测：读 GitHub Releases 最新版本并与当前版本比较。

比原来那份示例更稳的地方：
- 版本号补零比较，1.2 与 1.2.0 视为相同，不会误报，也不会把降级当更新；
- 区分 404（还没发 Release）/ 403（GitHub 匿名限额 60 次/小时）/网络错误，给中文提示；
- 结果缓存 6 小时，启动检查不会反复打接口；
- 同时找出 Release 里附带的安装包（.exe）下载地址；
- 只用标准库 urllib，不额外依赖 requests。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REPO = "xongge/StardewModManager"
API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
CACHE_TTL = 6 * 3600


class UpdateError(RuntimeError):
    pass


def _ver(text: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(text or ""))[:4])


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新（补零比较）。"""
    a, b = _ver(latest), _ver(current)
    if not a:
        return False
    if not b:
        return True
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_latest(repo: str = DEFAULT_REPO, timeout: int = 15) -> dict:
    repo = (repo or DEFAULT_REPO).strip().strip("/")
    if repo.count("/") != 1:
        raise UpdateError(f"仓库地址不对：{repo}（应形如 用户名/仓库名）")
    req = urllib.request.Request(
        API_LATEST.format(repo=repo),
        headers={"User-Agent": "StardewModManager", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("仓库里还没有发布 Release（或仓库地址写错了）") from exc
        if exc.code == 403:
            raise UpdateError("GitHub 接口受限（匿名每小时 60 次），稍后再试") from exc
        raise UpdateError(f"HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(f"网络错误：{exc}") from exc

    tag = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    assets = [
        {
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": a.get("size") or 0,
        }
        for a in (data.get("assets") or [])
    ]
    installer = ""
    for a in assets:
        if a["name"].lower().endswith(".exe"):
            installer = a["url"]
            break
    return {
        "version": tag,
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
        "page": data.get("html_url") or f"https://github.com/{repo}/releases",
        "published": data.get("published_at") or "",
        "assets": assets,
        "installer_url": installer,
        "repo": repo,
    }


class AppUpdateCache:
    """把检查结果写到磁盘，避免频繁请求。"""

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

    def fresh(self, ttl: int = CACHE_TTL):
        info = self.data.get("latest")
        if not isinstance(info, dict):
            return None
        if time.time() - float(self.data.get("checked") or 0) > ttl:
            return None
        return info

    def put(self, info: dict) -> None:
        self.data["latest"] = info
        self.data["checked"] = time.time()
        self.save()


def check(current: str, repo: str = DEFAULT_REPO, cache: AppUpdateCache | None = None,
          ttl: int = CACHE_TTL, force: bool = False) -> dict:
    """检查是否有新版本。返回 {has_update, latest, current, page, installer_url, notes, ...}"""
    info = None
    if cache is not None and not force:
        info = cache.fresh(ttl)
    from_cache = info is not None
    if info is None:
        info = fetch_latest(repo)
        if cache is not None:
            cache.put(info)
    latest = info.get("version") or ""
    return {
        "has_update": is_newer(latest, current),
        "latest": latest,
        "current": current,
        "page": info.get("page") or "",
        "installer_url": info.get("installer_url") or "",
        "notes": info.get("notes") or "",
        "name": info.get("name") or latest,
        "published": info.get("published") or "",
        "from_cache": from_cache,
        "repo": info.get("repo") or repo,
    }
