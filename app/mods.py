"""Mod 扫描 / manifest.json 解析 / 启用停用（移动文件夹）。"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAMES = ("manifest.json",)
KIND_LIB = "框架 / 库"
KIND_PACK = "内容包"
KIND_FUNC = "功能模组"
KIND_OTHER = "其他"
KINDS = [KIND_FUNC, KIND_PACK, KIND_LIB, KIND_OTHER]


# ---------------------------------------------------------------- JSON 解析
def tolerant_json(text: str):
    """容忍 BOM / // 注释 / /* */ 注释 / 尾随逗号的 JSON 解析。"""
    text = text.lstrip("\ufeff")
    out: list[str] = []
    i, n, in_str, esc = 0, len(text), False, False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    s = "".join(out)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return json.loads(s)


def find_manifest(folder: Path):
    try:
        for child in folder.iterdir():
            if child.is_file() and child.name.lower() in MANIFEST_NAMES:
                return child
    except OSError:
        pass
    return None


def read_manifest(folder: Path):
    """返回 (字典, 错误信息)。"""
    mp = find_manifest(folder)
    if mp is None:
        return None, "未找到 manifest.json"
    try:
        raw = mp.read_bytes()
    except OSError as exc:
        return None, f"无法读取 manifest.json：{exc}"
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return tolerant_json(raw.decode(enc)), None
        except Exception as exc:  # noqa: BLE001
            last = exc
    return None, f"manifest.json 解析失败：{last}"


# ---------------------------------------------------------------- 数据模型
@dataclass
class Problem:
    severity: str  # error / warn / info
    text: str


@dataclass
class Mod:
    folder: Path
    folder_name: str
    enabled: bool
    name: str = ""
    author: str = ""
    version: str = ""
    description: str = ""
    unique_id: str = ""
    update_keys: list = field(default_factory=list)
    min_api: str = ""
    content_pack_for: str = ""
    entry_dll: str = ""
    dependencies: list = field(default_factory=list)
    category: str = ""
    kind: str = KIND_OTHER
    problems: list = field(default_factory=list)
    zh_name: str = ""      # Mod 自带 i18n 里的中文名（如果有）
    manifest_path = None

    @property
    def has_error(self) -> bool:
        return any(p.severity == "error" for p in self.problems)

    @property
    def has_warn(self) -> bool:
        return any(p.severity == "warn" for p in self.problems)

    @property
    def display_version(self) -> str:
        return self.version or "-"


def _iter_mod_dirs(root: Path):
    if not root or not root.is_dir():
        return
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if find_manifest(entry) is not None:
            yield entry
            continue
        # SMAPI 支持 Mods/分组目录/具体Mod 的一层嵌套
        try:
            subs = sorted(entry.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for sub in subs:
            if sub.is_dir() and find_manifest(sub) is not None:
                yield sub


def _parse_version(text: str):
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(x) for x in nums[:4]) if nums else ()


def _version_gt(a: str, b: str) -> bool:
    return _parse_version(a) > _parse_version(b)


def _load_one(folder: Path, enabled: bool) -> Mod:
    mod = Mod(folder=folder, folder_name=folder.name, enabled=enabled)
    mod.manifest_path = find_manifest(folder)
    data, err = read_manifest(folder)
    if err:
        mod.name = folder.name
        mod.problems.append(Problem("error", err))
        return mod
    if not isinstance(data, dict):
        mod.name = folder.name
        mod.problems.append(Problem("error", "manifest.json 根节点不是对象"))
        return mod

    mod.name = str(data.get("Name") or folder.name).strip()
    mod.author = str(data.get("Author") or "").strip()
    mod.version = str(data.get("Version") or "").strip()
    mod.description = str(data.get("Description") or "").strip()
    mod.unique_id = str(data.get("UniqueID") or "").strip()
    mod.min_api = str(data.get("MinimumApiVersion") or "").strip()
    mod.entry_dll = str(data.get("EntryDll") or "").strip()
    cp = data.get("ContentPackFor")
    if isinstance(cp, dict):
        mod.content_pack_for = str(cp.get("UniqueID") or "").strip()
    elif isinstance(cp, str):
        mod.content_pack_for = cp.strip()

    keys = data.get("UpdateKeys") or []
    if isinstance(keys, str):
        keys = [keys]
    if isinstance(keys, list):
        mod.update_keys = [str(k) for k in keys if k]

    deps = data.get("Dependencies") or []
    if isinstance(deps, dict):
        deps = [deps]
    if isinstance(deps, list):
        for d in deps:
            if isinstance(d, dict) and d.get("UniqueID"):
                mod.dependencies.append(
                    {
                        "id": str(d.get("UniqueID")),
                        "required": bool(d.get("IsRequired", True)),
                        "min": str(d.get("MinimumVersion") or ""),
                    }
                )
    mod._raw_deps = deps  # type: ignore[attr-defined]
    for key, label in (("Name", "名称"), ("Author", "作者"), ("Version", "版本"), ("UniqueID", "UniqueID")):
        if not str(data.get(key) or "").strip():
            mod.problems.append(Problem("warn", f"manifest 缺少 {label}"))
    return mod


def scan(mods_dir: Path | None, disabled_dir: Path | None, smapi_version: str = "") -> list:
    """扫描启用目录与停用目录，返回 Mod 列表（含依赖/重复等检查）。"""
    mods: list = []
    if mods_dir:
        for d in _iter_mod_dirs(Path(mods_dir)):
            mods.append(_load_one(d, True))
    if disabled_dir:
        for d in _iter_mod_dirs(Path(disabled_dir)):
            mods.append(_load_one(d, False))

    installed_ids = {m.unique_id.lower() for m in mods if m.unique_id and m.enabled}

    # 依赖识别：谁被依赖（或被当作内容包框架）谁就是框架/库
    providers = set()
    for m in mods:
        for dep in m.dependencies:
            providers.add(dep["id"].lower())
        if m.content_pack_for:
            providers.add(m.content_pack_for.lower())

    seen: dict = {}
    for m in mods:
        uid = m.unique_id.lower()
        if uid:
            if uid in seen:
                m.problems.append(Problem("error", f"UniqueID 与「{seen[uid]}」重复"))
                for other in mods:
                    if other is not m and other.unique_id.lower() == uid:
                        if not other.has_error:
                            other.problems.append(Problem("error", f"UniqueID 与「{m.name}」重复"))
            else:
                seen[uid] = m.name
        # 类型
        if uid and uid in providers:
            m.kind = KIND_LIB
        elif m.content_pack_for:
            m.kind = KIND_PACK
        elif m.entry_dll:
            m.kind = KIND_FUNC
        else:
            m.kind = KIND_OTHER
        # 依赖检查
        for dep in m.dependencies:
            did = dep["id"].lower()
            if did in ("pathoschild.smapi", "smapi"):
                continue
            if did and did not in installed_ids:
                m.problems.append(
                    Problem("warn" if dep["required"] else "info", f"缺少前置：{dep['id']}")
                )
        if m.content_pack_for and m.content_pack_for.lower() not in installed_ids:
            m.problems.append(Problem("warn", f"缺少内容包框架：{m.content_pack_for}"))
        if m.min_api and smapi_version and _version_gt(m.min_api, smapi_version):
            m.problems.append(Problem("warn", f"需要 SMAPI {m.min_api}，当前 {smapi_version}"))
        if not m.update_keys:
            m.problems.append(Problem("info", "没有 UpdateKeys，无法自动检查更新"))
    mods.sort(key=lambda m: (not m.enabled, m.name.lower()))
    return mods


# ---------------------------------------------------------------- 启用 / 停用
def disabled_root(mods_dir: Path, name: str) -> Path:
    return Path(mods_dir).parent / name


def _unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    for i in range(2, 999):
        cand = dest.with_name(f"{dest.name} ({i})")
        if not cand.exists():
            return cand
    return dest


def toggle_mod(mod: Mod, disabled_name: str, mods_dir: Path, do_enable: bool):
    """返回 (成功, 消息)。"""
    src = Path(mod.folder)
    mods_dir = Path(mods_dir)
    droot = disabled_root(mods_dir, disabled_name)
    if do_enable:
        droot.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(mods_dir / src.name)
    else:
        droot.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(droot / src.name)
    try:
        shutil.move(str(src), str(dest))
        return True, dest.name
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------- manifest 名称
NAME_FIELD_RE = re.compile(r'("Name"\s*:\s*")((?:[^"\\]|\\.)*)(")')


def manifest_backup(folder: Path) -> Path | None:
    mp = find_manifest(Path(folder))
    if mp is None:
        return None
    return mp.with_name(mp.name + ".original")


def has_manifest_backup(folder: Path) -> bool:
    bak = manifest_backup(folder)
    return bool(bak and bak.exists())


def write_manifest_name(folder: Path, new_name: str):
    """只替换 manifest.json 里的 Name 值，保留文件其它内容（含注释）。

    第一次修改前会备份成 manifest.json.original。
    返回 (成功, 消息)。
    """
    mp = find_manifest(Path(folder))
    if mp is None:
        return False, "找不到 manifest.json"
    try:
        raw = mp.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            raw = mp.read_text(encoding="gbk")
        except Exception as exc:  # noqa: BLE001
            return False, f"读取失败：{exc}"
    except OSError as exc:
        return False, f"读取失败：{exc}"
    m = NAME_FIELD_RE.search(raw)
    if not m:
        return False, "manifest.json 里没有 Name 字段"
    bak = mp.with_name(mp.name + ".original")
    try:
        if not bak.exists():
            shutil.copy2(mp, bak)
        escaped = str(new_name).replace("\\", "\\\\").replace('"', '\\"')
        new_raw = raw[: m.start(2)] + escaped + raw[m.end(2):]
        mp.write_text(new_raw, encoding="utf-8")
        return True, str(new_name)
    except OSError as exc:
        return False, f"写入失败：{exc}（可能游戏目录没有写权限）"


def restore_manifest_name(folder: Path):
    """把 Name 恢复成备份里的原名。"""
    mp = find_manifest(Path(folder))
    if mp is None:
        return False, "找不到 manifest.json"
    bak = mp.with_name(mp.name + ".original")
    if not bak.exists():
        return False, "没有备份（说明这个名称不是本程序改的）"
    try:
        shutil.copy2(bak, mp)
        return True, ""
    except OSError as exc:
        return False, f"恢复失败：{exc}"
