"""AI 汉化：调用 OpenAI 兼容接口（商汤 SenseNova）批量翻译 Mod 名称。

要点：
1. 所有待翻译名称**一次性**放进同一个请求；
2. 每个条目都带 UniqueID，返回后按 id 精确回填，绝不会把 A 的名字给到 B；
3. 结果写入本地缓存（%APPDATA%\\StardewModManager\\name_map.json），
   以后只翻译新增/变化的模组，省 token。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://token.sensenova.cn/v1"
DEFAULT_MODEL = ""   # 留空 = 由探测/回退逻辑自动挑选
# 常见模型名，用作候选；接口能列出的模型会优先使用。
KNOWN_MODELS = [
    "sensenova-6.8-flash-lite",
    "deepseek-v4-flash",
    "glm-5.2",
    "sensenova-6.7-flash-lite",
    "sensenova-u1-fast",
    "sensenova-u1.5-lite",
    "deepseek-v4-pro",
    "kimi-k3",
]

SYSTEM_PROMPT = (
    "你是《星露谷物语》Mod 名称本地化专家。给你一个 JSON 数组，每项含 id 与 name。"
    "请把 name 翻译/意译成简体中文（保留版本号、作者名、[CP]、[FTM] 等标签），"
    "并严格按 id 一一对应返回同样的 JSON 数组，元素格式 {\"id\": 原 id, \"zh\": 中文名}。"
    "必须包含输入中的每一个 id，不许合并、不许改动 id、不许遗漏，只输出 JSON，不要解释。"
)


class AIError(RuntimeError):
    pass


def _endpoint(base: str, path: str) -> str:
    base = (base or DEFAULT_BASE).strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base + path


def request_json(url: str, key: str, payload=None, method: str = "GET", timeout: int = 120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AIError(f"HTTP {exc.code}：{detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AIError(str(exc)) from exc


def list_models(base: str, key: str) -> list:
    data = request_json(_endpoint(base, "/models"), key, timeout=30)
    return [m.get("id") for m in (data.get("data") or []) if m.get("id")]


def chat(base: str, key: str, model: str, messages: list, max_tokens: int = 4096,
         temperature: float | None = 0.2, _retry: bool = True) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        data = request_json(_endpoint(base, "/chat/completions"), key, payload, method="POST")
    except AIError as exc:
        msg = str(exc)
        # 少数模型只接受 temperature=1 / 不接受 max_tokens，被拒就去掉重试
        if "emperature" in msg:
            payload.pop("temperature", None)
            data = request_json(_endpoint(base, "/chat/completions"), key, payload, method="POST")
        elif "max_tokens" in msg:
            payload.pop("max_tokens", None)
            data = request_json(_endpoint(base, "/chat/completions"), key, payload, method="POST")
        else:
            raise
    try:
        message = data["choices"][0].get("message") or {}
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"接口返回格式异常：{str(data)[:200]}") from exc

    content = (message.get("content") or "").strip()
    if not content:
        # 少数模型偶尔只返回推理内容（content 为空），先重试一次
        if _retry:
            return chat(base, key, model, messages, max_tokens, temperature=None, _retry=False)
        reasoning = (message.get("reasoning") or message.get("reasoning_content") or "").strip()
        if reasoning:
            return reasoning
        raise AIError(f"模型 {model} 没有返回内容，请重试或换一个模型")
    return content


def is_model_error(exc: Exception) -> bool:
    """判断是不是“这个模型当前用不了”（换一个模型就能解决）。"""
    text = str(exc).lower()
    if "model" not in text:
        return False
    return any(k in text for k in ("not found", "not_found", "route", "不存在", "no permission", "not allowed"))


def probe_model(base: str, key: str, model: str, timeout: int = 40) -> tuple:
    """发一个极小的请求，确认该模型当前是否可用（只看 HTTP 是否成功）。"""
    try:
        request_json(
            _endpoint(base, "/chat/completions"),
            key,
            {
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 16,
            },
            method="POST",
            timeout=timeout,
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def probe_models(base: str, key: str, candidates: list, limit: int = 12) -> tuple:
    """逐个探测，返回 (可用模型列表, 失败的 {模型: 原因})。"""
    ok, bad, seen = [], {}, set()
    for model in candidates[:limit]:
        if not model or model in seen:
            continue
        seen.add(model)
        good, err = probe_model(base, key, model)
        if good:
            ok.append(model)
        else:
            bad[model] = err
    return ok, bad


def parse_pairs(text: str) -> dict:
    """从模型回复里抽出 {id: 中文}。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise AIError("模型没有返回 JSON：" + text[:200])
    raw = m.group(0)
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        # 兜底：逐个对象抓取
        pairs = {}
        for obj in re.finditer(r"\{[^{}]*\}", raw):
            try:
                item = json.loads(obj.group(0))
            except Exception:  # noqa: BLE001
                continue
            sid = item.get("id") or item.get("uid") or item.get("UniqueID")
            zh = item.get("zh") or item.get("name") or item.get("translation")
            if sid and zh:
                pairs[str(sid)] = str(zh)
        if pairs:
            return pairs
        raise AIError("无法解析模型返回的 JSON") from None
    if isinstance(data, dict):
        data = data.get("data") or data.get("items") or data.get("result") or []
    pairs = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        sid = item.get("id") or item.get("uid") or item.get("UniqueID")
        zh = item.get("zh") or item.get("name") or item.get("translation")
        if sid and zh:
            pairs[str(sid).strip()] = str(zh).strip()
    if not pairs:
        raise AIError("模型返回的 JSON 里没有可用的 id/zh")
    return pairs


def translate_names(entries: list, base: str, key: str, model: str, max_tokens: int = 8192,
                    fallbacks: list | None = None) -> dict:
    """一次性翻译全部条目（返回 {id: 中文}）。"""
    pairs, _model = translate_names_ex(entries, base, key, model, max_tokens, fallbacks)
    return pairs


def translate_names_ex(entries: list, base: str, key: str, model: str, max_tokens: int = 8192,
                       fallbacks: list | None = None) -> tuple:
    """一次性翻译全部条目。返回 ({id: 中文}, 实际使用的模型)。

    如果当前模型不可用（404 model not found 之类），会自动换用列表里其它模型，
    这样 Key 能访问哪些模型变了也不会影响使用。
    """
    if not entries:
        return {}, model or ""
    if not key:
        raise AIError("没有配置 API Key，请到「设置」里填写")

    candidates = []
    pool = list(fallbacks or [])
    if not pool:
        # 用户没在设置里探测过：先问接口能列哪些模型，再退到内置候选
        try:
            pool = list_models(base, key)[:6]
        except Exception:  # noqa: BLE001
            pool = []
    for m in [model, *pool, *KNOWN_MODELS]:
        if m and m not in candidates:
            candidates.append(m)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                [{"id": e["id"], "name": e["name"]} for e in entries], ensure_ascii=False
            ),
        },
    ]
    asked = {str(e["id"]) for e in entries}
    errors = []
    for cand in candidates:
        try:
            content = chat(base, key, cand, messages, max_tokens=max_tokens)
        except AIError as exc:
            errors.append(f"{cand}: {exc}")
            if is_model_error(exc):
                continue  # 换下一个模型
            raise
        pairs = parse_pairs(content)
        return {k: v for k, v in pairs.items() if k in asked}, cand
    raise AIError(
        "这些模型当前都不可用：\n" + "\n".join(errors[:6])
        + "\n\n请到「设置 → AI 汉化」点「测试连接并自动选择模型」。"
    )


def translate_text(text: str, base: str, key: str, model: str, fallbacks: list | None = None,
                   instruction: str = "") -> tuple:
    """把一段文本（例如 SMAPI 的更新日志）翻译成简体中文。

    返回 (译文, 实际使用的模型)。同样会在一批候选模型里自动挑能用的。
    """
    text = (text or "").strip()
    if not text:
        return "", model or ""
    if not key:
        raise AIError("没有配置 API Key，请到「设置」里填写")

    candidates = []
    pool = list(fallbacks or [])
    if not pool:
        try:
            pool = list_models(base, key)[:6]
        except Exception:  # noqa: BLE001
            pool = []
    for m in [model, *pool, *KNOWN_MODELS]:
        if m and m not in candidates:
            candidates.append(m)

    prompt = instruction or (
        "把下面的更新日志翻译成简体中文，保留原有的 Markdown 结构（标题、列表、链接、代码），"
        "专有名词（Mod 名、文件名、SMAPI/Nexus 等）保留原文，不要添加解释，只输出译文。"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text[:12000]},
    ]
    errors = []
    for cand in candidates:
        try:
            out = chat(base, key, cand, messages, max_tokens=8192)
        except AIError as exc:
            errors.append(f"{cand}: {exc}")
            if is_model_error(exc):
                continue
            raise
        return out.strip(), cand
    raise AIError("这些模型当前都不可用：\n" + "\n".join(errors[:6]))


# ---------------------------------------------------------------- 本地缓存
class NameCache:
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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    def get(self, unique_id: str, original: str = "") -> str:
        item = self.data.get(unique_id)
        if isinstance(item, dict):
            if original and item.get("src") and item["src"] != original:
                return ""  # 原名变了，需要重新翻译
            return item.get("zh") or ""
        return ""

    def put(self, unique_id: str, original: str, translated: str) -> None:
        self.data[unique_id] = {"src": original, "zh": translated}

    def pending(self, mods: list) -> list:
        out = []
        for m in mods:
            if not m.unique_id or not m.name:
                continue
            if getattr(m, "zh_name", ""):
                continue  # Mod 自带中文名，不用花 token
            if not self.get(m.unique_id, m.name):
                out.append({"id": m.unique_id, "name": m.name})
        return out
