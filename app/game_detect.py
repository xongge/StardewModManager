from __future__ import annotations

"""游戏目录探测：Steam 库、GOG、多盘符、SMAPI 残留目录识别。"""
import re
from pathlib import Path

from .game_constants import SMAPI_EXE, VANILLA_EXE

def _steam_library_dirs() -> list:
    """从注册表读所有 Steam 库目录（不写死任何人的盘符）。"""
    dirs = []
    try:
        import winreg

        keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        steam_roots = []
        for root, path, name in keys:
            try:
                with winreg.OpenKey(root, path) as key:
                    value = str(winreg.QueryValueEx(key, name)[0])
                    if value:
                        steam_roots.append(Path(value.replace("/", "\\")))
            except OSError:
                continue
        for lib in steam_roots:
            dirs.append(lib / "steamapps" / "common" / "Stardew Valley")
            vdf = lib / "steamapps" / "libraryfolders.vdf"
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(m.group(1).replace("\\\\", "\\"))
                    dirs.append(p / "steamapps" / "common" / "Stardew Valley")
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return dirs


def _fallback_dirs() -> list:
    """常见安装位置：各盘符 + Steam 注册表 + GOG 默认目录。"""
    dirs = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley"),
        Path(r"C:\Program Files\Steam\steamapps\common\Stardew Valley"),
        Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Stardew Valley"),
        Path(r"C:\GOG Games\Stardew Valley"),
    ]
    for letter in "CDEFGHIJ":
        dirs.append(Path(f"{letter}:\\Steam\\steamapps\\common\\Stardew Valley"))
        dirs.append(Path(f"{letter}:\\SteamLibrary\\steamapps\\common\\Stardew Valley"))
        dirs.append(Path(f"{letter}:\\Games\\Stardew Valley"))
    dirs.extend(_steam_library_dirs())
    out, seen = [], set()
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

_FALLBACK_DIRS = _fallback_dirs()

def _steam_roots():
    roots = []
    try:
        import winreg
    except Exception:  # noqa: BLE001
        return roots
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as k:
                for value in ("SteamPath", "InstallPath"):
                    try:
                        v, _ = winreg.QueryValueEx(k, value)
                        if v:
                            roots.append(Path(v))
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def _library_paths(steam_root: Path):
    out = []
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                out.append(Path(m.group(1).replace("\\\\", "\\")))
        except Exception:  # noqa: BLE001
            pass
    out.append(steam_root)
    return out


def _valid_game_dir(p: Path) -> bool:
    """只有含游戏本体的目录才算游戏目录（只有 SMAPI 残留的目录不算）。"""
    try:
        return (p / VANILLA_EXE).exists()
    except OSError:
        return False


def _score_game_dir(p: Path) -> int:
    score = 0
    if (p / VANILLA_EXE).exists():
        score += 8
    if (p / "Stardew Valley.dll").exists():
        score += 4
    if (p / "Content").is_dir():
        score += 2
    if (p / SMAPI_EXE).exists():
        score += 1
    if (p / "Mods").is_dir():
        score += 1
    return score


def iter_game_candidates() -> list:
    """所有可能的星露谷目录（Steam 各库 + 常见路径），去掉重复。"""
    out = []
    seen = set()

    def add(path):
        try:
            p = Path(path)
        except Exception:  # noqa: BLE001
            return
        key = str(p).lower().rstrip("\\/")
        if key and key not in seen:
            seen.add(key)
            out.append(p)

    for root in _steam_roots():
        for lib in _library_paths(root):
            add(Path(str(lib)) / "steamapps" / "common" / "Stardew Valley")
    for raw in _FALLBACK_DIRS:
        add(raw)
    return out


def detect_game_dir() -> str:
    """挑出真正的游戏目录（优先含 Stardew Valley.exe，其次内容最完整的）。"""
    best, best_score = "", 0
    for p in iter_game_candidates():
        if not p.is_dir():
            continue
        score = _score_game_dir(p)
        if score > best_score:
            best, best_score = str(p), score
    # 至少要能看到游戏本体，否则不算找到
    return best if best_score >= 8 else ""


def find_smapi_only_dirs() -> list:
    """只有 SMAPI 没有游戏本体的目录（常见于换盘后留下的残留）。"""
    out = []
    for p in iter_game_candidates():
        if p.is_dir() and not (p / VANILLA_EXE).exists() and (p / SMAPI_EXE).exists():
            out.append(str(p))
    return out


def validate_game_dir(game_dir: str) -> dict:
    gd = Path(game_dir) if game_dir else None
    info = {"path": str(gd or ""), "exists": False, "has_game": False, "has_smapi": False, "reason": ""}
    if not gd or not gd.is_dir():
        info["reason"] = "目录不存在"
        return info
    info["exists"] = True
    info["has_game"] = (gd / VANILLA_EXE).exists()
    info["has_smapi"] = (gd / SMAPI_EXE).exists()
    if not info["has_game"]:
        info["reason"] = "这个目录里没有游戏本体 Stardew Valley.exe（只有 SMAPI 的残留文件）"
    return info


def default_mods_dir(game_dir: str) -> str:
    return str(Path(game_dir) / "Mods") if game_dir else ""

VANILLA_BACKUP_SUFFIXES = (".wjdl.backup", ".bak", ".orig", ".original", ".vanilla", ".backup")


def find_vanilla_exe(game_dir: str) -> tuple:
    """找“真正的原版启动文件”。

    有些第三方工具（例如带 .wjdl.backup 的那种）会把 Stardew Valley.exe 换成
    加载 SMAPI 的启动器，这时点「原版启动」其实还是会带 Mod。这里优先使用备份文件。
    返回 (路径, 说明文字)。
    """
    gd = Path(game_dir) if game_dir else None
    if not gd:
        return "", ""
    main = gd / VANILLA_EXE
    for suffix in VANILLA_BACKUP_SUFFIXES:
        cand = gd / (VANILLA_EXE + suffix)
        if cand.exists():
            return str(cand), f"{VANILLA_EXE} 已被第三方工具替换，原版启动改用备份：{cand.name}"
    return str(main), ""
