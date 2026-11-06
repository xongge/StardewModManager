"""模组数据操作层：过滤、启停、写入/恢复中文名。

页面只负责展示与交互（弹窗、线程、状态栏），业务规则都在这里，
便于单独测试，也方便以后换 UI。
"""
from __future__ import annotations

from pathlib import Path

from .. import mods as modlib

CAT_ALL = "全部 Mod"
CAT_ON = "已启用"
CAT_OFF = "已停用"
CAT_ISSUE = "有问题的"
CAT_UPDATE = "可更新的"
CATS_FIXED = (CAT_ALL, CAT_ON, CAT_OFF, CAT_ISSUE, CAT_UPDATE)


def category_counts(mods) -> dict:
    """各类分类下的数量（左侧分类列表用）。"""
    counts = {
        CAT_ALL: len(mods),
        CAT_ON: sum(1 for m in mods if m.enabled),
        CAT_OFF: sum(1 for m in mods if not m.enabled),
        CAT_ISSUE: sum(1 for m in mods if m.problems),
    }
    return counts


def kind_counts(mods) -> dict:
    out: dict = {}
    for mod in mods:
        out[mod.kind] = out.get(mod.kind, 0) + 1
    return out


def match(mod, cat: str, keyword: str, updates: dict, translated_name, kinds) -> bool:
    """单个 Mod 是否命中当前分类 + 搜索词。"""
    if cat == CAT_ON and not mod.enabled:
        return False
    if cat == CAT_OFF and mod.enabled:
        return False
    if cat == CAT_ISSUE and not mod.problems:
        return False
    if cat == CAT_UPDATE and (updates.get(mod.unique_id) or {}).get("status") != "new":
        return False
    if cat in kinds and mod.kind != cat:
        return False
    if keyword:
        zh = translated_name(mod)
        hay = (
            f"{mod.name} {zh} {getattr(mod, 'zh_name', '')} {mod.author} "
            f"{mod.unique_id} {mod.folder_name} {mod.description}"
        ).lower()
        if keyword not in hay:
            return False
    return True


def filter_mods(mods, cat: str, keyword: str, updates: dict, translated_name, kinds) -> list:
    return [m for m in mods if match(m, cat, keyword, updates, translated_name, kinds)]


# ---------------------------------------------------------------- 启用 / 停用
def toggle_one(mod, want_enabled: bool, disabled_name: str, mods_dir) -> tuple[bool, str]:
    """切换单个 Mod 的启用状态（移动文件夹，不删除任何文件）。"""
    if mods_dir is None:
        return False, "未设置 Mod 文件夹"
    return modlib.toggle_mod(mod, disabled_name, mods_dir, want_enabled)


def bulk_toggle(mods, want_enabled: bool, disabled_name: str, mods_dir) -> tuple[int, int]:
    """批量切换，返回 (成功数, 失败数)。"""
    ok = fail = 0
    for mod in mods:
        good, _msg = modlib.toggle_mod(mod, disabled_name, mods_dir, want_enabled)
        if good:
            ok += 1
        else:
            fail += 1
    return ok, fail


# ---------------------------------------------------------------- 中文名写入
def name_pairs(mods, translated_name) -> list:
    """[(mod, 中文名)] —— 只收真正有中文名且与原名不同的。"""
    pairs = []
    for mod in mods:
        zh = translated_name(mod)
        if zh and zh != mod.name:
            pairs.append((mod, zh))
    return pairs


def write_names(pairs) -> tuple[int, int, list]:
    """把中文名写进 manifest（自动备份），返回 (成功, 失败, 错误列表)。"""
    ok = fail = 0
    errors: list = []
    for mod, zh in pairs:
        good, msg = modlib.write_manifest_name(Path(mod.folder), zh)
        if good:
            ok += 1
        else:
            fail += 1
            errors.append(f"{mod.folder_name}: {msg}")
    return ok, fail, errors


def restore_targets(mods) -> list:
    return [m for m in mods if modlib.has_manifest_backup(Path(m.folder))]


def restore_names(mods) -> tuple[int, int]:
    """从 manifest.json.original 恢复原名，返回 (成功, 失败)。"""
    ok = fail = 0
    for mod in mods:
        good, _msg = modlib.restore_manifest_name(Path(mod.folder))
        ok += 1 if good else 0
        fail += 0 if good else 1
    return ok, fail
