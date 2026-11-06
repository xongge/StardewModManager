"""可选加速核心：调用 C 库（sdvcore.dll）扫描 Mods 目录。

没有 DLL、加载失败或返回异常时，调用方会自动回退到纯 Python 实现，
所以这是个"锦上添花"的加速层，不影响任何现有功能。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

_lib = None
_loaded = False
_error = ""


def _candidate_paths() -> list:
    here = Path(__file__).resolve().parent          # app/core
    root = here.parent.parent                       # 仓库根 / 安装根
    out = []
    env = os.environ.get("SDVMM_CORE_DLL")
    if env:
        out.append(Path(env))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass) / "sdvcore.dll")
    exe_dir = Path(sys.executable).resolve().parent
    out += [
        exe_dir / "sdvcore.dll",
        exe_dir / "_internal" / "sdvcore.dll",
        root / ".build" / "c" / "sdvcore.dll",
        root / "sdvcore.dll",
        here / "sdvcore.dll",
    ]
    return out


def load() -> bool:
    """加载 DLL；返回是否可用。只尝试一次。"""
    global _lib, _loaded, _error
    if _loaded:
        return _lib is not None
    _loaded = True
    for path in _candidate_paths():
        try:
            if not path.exists():
                continue
            lib = ctypes.WinDLL(str(path))
            lib.sdv_scan_dir.argtypes = [ctypes.c_wchar_p]
            lib.sdv_scan_dir.restype = ctypes.c_void_p
            lib.sdv_count_mods.argtypes = [ctypes.c_wchar_p]
            lib.sdv_count_mods.restype = ctypes.c_int
            lib.sdv_decode_utf16.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
            lib.sdv_decode_utf16.restype = ctypes.c_void_p
            lib.sdv_free.argtypes = [ctypes.c_void_p]
            lib.sdv_free.restype = None
            lib.sdv_classifier_new.restype = ctypes.c_void_p
            lib.sdv_classifier_level.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.sdv_classifier_level.restype = ctypes.c_int
            lib.sdv_classifier_free.argtypes = [ctypes.c_void_p]
            lib.sdv_classifier_free.restype = None
            _lib = lib
            _error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            _error = f"{path.name}: {exc}"
            continue
    return False


def available() -> bool:
    return load()


def error() -> str:
    load()
    return _error


def _take_string(ptr) -> str:
    if not ptr:
        return ""
    try:
        return ctypes.wstring_at(ptr) if False else ctypes.string_at(ptr).decode("utf-8", "replace")
    finally:
        _lib.sdv_free(ptr)


def scan_root(root) -> list | None:
    """扫描一个目录，返回条目列表；失败返回 None（调用方回退 Python）。"""
    if not available():
        return None
    try:
        ptr = _lib.sdv_scan_dir(str(root))
        if not ptr:
            return None
        text = ctypes.string_at(ptr).decode("utf-8", "replace")
        _lib.sdv_free(ptr)
        data = json.loads(text)
        if not isinstance(data, list):
            return None
        return [item for item in data if isinstance(item, dict)]
    except Exception:  # noqa: BLE001
        return None


def count_root(root) -> int:
    if not available():
        return -1
    try:
        return int(_lib.sdv_count_mods(str(root)))
    except Exception:  # noqa: BLE001
        return -1


def decode_utf16(data: bytes) -> str | None:
    """整块 UTF-16 转 UTF-8（仅用于完整缓冲区）。"""
    if not available() or not data:
        return None
    try:
        ptr = _lib.sdv_decode_utf16(data, len(data))
        if not ptr:
            return None
        text = ctypes.string_at(ptr).decode("utf-8", "replace")
        _lib.sdv_free(ptr)
        return text
    except Exception:  # noqa: BLE001
        return None


class Classifier:
    """有状态的输出分级器（与 Python 版 LevelTracker 行为一致）。"""

    _NAMES = {0: "info", 1: "warn", 2: "error", 3: "trace"}

    def __init__(self) -> None:
        self._impl = _lib.sdv_classifier_new() if available() else None

    def level(self, line: str) -> str:
        if not self._impl:
            return "info"
        try:
            return self._NAMES.get(int(_lib.sdv_classifier_level(self._impl, line.encode("utf-8", "replace"))), "info")
        except Exception:  # noqa: BLE001
            return "info"

    def close(self) -> None:
        if self._impl:
            try:
                _lib.sdv_classifier_free(self._impl)
            except Exception:  # noqa: BLE001
                pass
            self._impl = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
