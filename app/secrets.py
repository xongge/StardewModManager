"""密钥加密：用 Windows DPAPI（CryptProtectData）加密 API Key 等敏感信息。

- 密文与「当前 Windows 用户 + 这台电脑」绑定，把程序目录复制到别的电脑也无法解密；
- config.json 里只保存密文（*_dpapi 字段），不会出现明文 sk-xxx；
- 不是 Windows 或加密失败时自动退回明文保存，保证功能可用。
"""
from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

_IS_WINDOWS = sys.platform == "win32"
ENTROPY = b"StardewModManager.v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def available() -> bool:
    return _IS_WINDOWS


def protect(text: str) -> str:
    """加密成 base64 字符串；失败返回空串。"""
    if not text:
        return ""
    if not _IS_WINDOWS:
        return ""
    try:
        data = text.encode("utf-8")
        blob_in, _keep = _make_blob(data)
        ent, _keep2 = _make_blob(ENTROPY)
        blob_out = _Blob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "StardewModManager",
            ctypes.byref(ent),
            None,
            None,
            0,
            ctypes.byref(blob_out),
        )
        if not ok:
            return ""
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return base64.b64encode(raw).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:  # noqa: BLE001
        return ""


def unprotect(blob_b64: str) -> str:
    """解密；失败（例如换了电脑/用户）返回空串。"""
    if not blob_b64 or not _IS_WINDOWS:
        return ""
    try:
        raw = base64.b64decode(blob_b64)
        blob_in, _keep = _make_blob(raw)
        ent, _keep2 = _make_blob(ENTROPY)
        blob_out = _Blob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, ctypes.byref(ent), None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return ""
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8", "replace")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:  # noqa: BLE001
        return ""
