"""读取 Mod 自己的配置文件（config.json）与 i18n 中文翻译，用于生成配置编辑界面。"""
from __future__ import annotations

import re
from pathlib import Path

from .mods import tolerant_json

I18N_DIRS = ("i18n", "assets/i18n")
I18N_PREFER = ["zh.json", "zh-CN.json", "zh_CN.json", "zh-Hans.json", "default.json", "en.json"]


def read_json(path: Path):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return tolerant_json(raw.decode(enc))  # 很多 Mod 的 json 带注释
        except Exception:  # noqa: BLE001
            continue
    return None


def find_config(mod_folder: Path) -> Path | None:
    p = Path(mod_folder) / "config.json"
    return p if p.exists() else None


def _i18n_dir(mod_folder: Path) -> Path | None:
    folder = Path(mod_folder)
    for rel in I18N_DIRS:
        d = folder / rel
        if d.is_dir():
            return d
    for d in folder.rglob("i18n"):
        if d.is_dir():
            return d
    return None


def load_i18n(mod_folder: Path) -> dict:
    """返回 {键: 文本}，另外附带小写索引 '_lower'；优先简体中文，其次默认语言。"""
    folder = Path(mod_folder)
    d = _i18n_dir(folder)
    merged: dict = {}
    if d is None:
        return merged
    files = {p.name.lower(): p for p in d.iterdir() if p.suffix.lower() == ".json"}
    order = [n for n in I18N_PREFER if n.lower() in files]
    order += [n for n in files if n not in [o.lower() for o in order]]
    for name in order:
        data = read_json(files[name])
        if not isinstance(data, dict):
            continue
        is_zh = name.lower().startswith("zh")
        for k, v in data.items():
            if not isinstance(v, str):
                continue
            if is_zh or k not in merged:
                merged[k] = v
    lower = {}
    for k, v in merged.items():
        lower.setdefault(str(k).lower(), v)
    merged["_lower"] = lower
    return merged


NAME_SUFFIXES = (".name", ".title", ".label", "")
DESC_SUFFIXES = (".description", ".desc", ".tooltip", ".tooltip-text", ".explanation", ".help")
# 各家 Mod 在 i18n 里用的前缀五花八门，这里都试一遍
PREFIXES = (
    "config.",
    "modconfigmenu.",
    "modconfig.",
    "gmcm.",
    "options.",
    "settings.",
    "menu.",
    "",
)


def key_variants(key: str) -> list:
    """同一个配置项在不同 Mod 里可能写成 enableGrass / automation-interval / is_enable_x。

    返回该键的多种写法（原样、全小写、连字符、下划线、去分隔符）。
    """
    k = str(key)
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", k)
    flat = re.sub(r"[^a-z0-9]+", "", k.lower())
    out = []
    for v in (
        k,
        k.lower(),
        "-".join(p.lower() for p in parts),
        "_".join(p.lower() for p in parts),
        flat,
    ):
        if v and v.lower() not in [o.lower() for o in out]:
            out.append(v)
    return out


def _find(lower: dict, key: str, suffixes, prefixes=PREFIXES) -> str:
    for variant in key_variants(key):
        for prefix in prefixes:
            for suffix in suffixes:
                hit = lower.get(f"{prefix}{variant}{suffix}".lower())
                if hit:
                    return hit
    return ""


def _lookup(i18n: dict, key: str) -> str:
    """按多种命名习惯（大小写 / 连字符 / 下划线 / 前缀 都不敏感）找中文名。"""
    return _find(i18n.get("_lower") or {}, key, NAME_SUFFIXES)


def _lookup_extra(i18n: dict, key: str) -> str:
    return _find(i18n.get("_lower") or {}, key, DESC_SUFFIXES)


def value_options(i18n: dict, key: str) -> list:
    """GMCM 枚举：config.<key>.values.<值>（也兼容 choices / options 与各种前缀）。"""
    lower = i18n.get("_lower") or {}
    for variant in key_variants(key):
        for prefix in PREFIXES:
            for mid in ("values.", "choices.", "options."):
                head = f"{prefix}{variant}.{mid}"
                hits = [
                    str(k)[len(head):]
                    for k in i18n
                    if k != "_lower" and str(k).lower().startswith(head.lower())
                ]
                if hits:
                    return sorted(set(hits))
    return []


def option_label(i18n: dict, key: str, value: str) -> str:
    lower = i18n.get("_lower") or {}
    for variant in key_variants(key):
        for prefix in PREFIXES:
            for mid in ("values.", "choices.", "options."):
                hit = lower.get(f"{prefix}{variant}.{mid}{value}".lower())
                if hit:
                    return hit
    return value


def localized_mod_name(mod_folder: Path) -> str:
    """Mod 自带的中文名：i18n/zh*.json 里的 mod-name / modname / name。"""
    folder = Path(mod_folder)
    d = _i18n_dir(folder)
    if d is None:
        return ""
    for f in sorted(d.iterdir()):
        if f.suffix.lower() != ".json" or not f.name.lower().startswith("zh"):
            continue
        data = read_json(f)
        if not isinstance(data, dict):
            continue
        lower = {str(k).lower(): v for k, v in data.items() if isinstance(v, str)}
        for cand in ("mod-name", "modname", "mod_name", "name"):
            if lower.get(cand):
                return str(lower[cand]).strip()
    return ""


def humanize(key: str) -> str:
    """把 camelCase / snake_case 的键变成可读英文。"""
    text = str(key).replace("_", " ").replace("-", " ")
    text = "".join((" " + c) if c.isupper() and i else c for i, c in enumerate(text))
    return " ".join(text.split()).strip() or str(key)


def describe_value(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "null"


def build_schema(config: dict, i18n: dict, extra_labels: dict | None = None) -> list:
    """把 config.json 变成界面描述。extra_labels 是 AI 翻译缓存 {键: 中文}。"""
    extra_labels = extra_labels or {}
    out = []
    for key, value in (config or {}).items():
        kind = describe_value(value)
        label = _lookup(i18n, key) or extra_labels.get(str(key), "")
        help_text = _lookup_extra(i18n, key)
        if kind == "dict":
            out.append(
                {
                    "key": key,
                    "label": label or humanize(key),
                    "i18n": bool(label),
                    "help": help_text,
                    "type": "group",
                    "children": build_schema(value, i18n, extra_labels),
                }
            )
            continue
        out.append(
            {
                "key": key,
                "label": label or humanize(key),
                "i18n": bool(label),
                "help": help_text,
                "type": kind,
                "value": value,
                "options": value_options(i18n, key),
            }
        )
    return out


def load_mod_config(mod_folder: Path):
    """返回 (config 字典 或 None, i18n 字典, config 路径)。"""
    folder = Path(mod_folder)
    path = find_config(folder)
    config = read_json(path) if path else None
    return (config if isinstance(config, dict) else None), load_i18n(folder), path


def save_mod_config(path: Path, data: dict) -> None:
    import json

    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

