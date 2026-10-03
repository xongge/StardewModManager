"""应用图标：优先用 config.json 里 icon 指定的文件，其次程序目录的 icon.ico，
最后用内置绘图生成，保证任务栏/窗口图标不再是 pythonw 的默认图标。
"""
from __future__ import annotations

import ctypes
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from .. import APP_ID
from ..config import app_dir

_cache: dict = {}


def resolve_icon_path(cfg=None) -> Path | None:
    """按 配置 -> 程序目录 的顺序找图标文件。"""
    names = []
    if cfg is not None:
        value = str(cfg.get("icon") or "").strip()
        if value:
            p = Path(value)
            names.append(p if p.is_absolute() else app_dir() / p)
    names += [app_dir() / "icon.ico", app_dir() / "icon.png"]
    for p in names:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _generated_pixmap(size: int) -> QPixmap:
    key = f"gen{size}"
    if key in _cache:
        return _cache[key]
    from ..icongen import render_rgba

    data = bytes(render_rgba(size))
    from PySide6.QtGui import QImage

    img = QImage(data, size, size, size * 4, QImage.Format_RGBA8888)
    pm = QPixmap.fromImage(img.copy())
    _cache[key] = pm
    return pm


def app_icon(cfg=None) -> QIcon:
    """返回应用图标（多尺寸）。"""
    if "icon" in _cache:
        return _cache["icon"]
    path = resolve_icon_path(cfg)
    icon = QIcon()
    if path is not None:
        if path.suffix.lower() == ".ico":
            icon = QIcon(str(path))
        else:
            pm = QPixmap(str(path))
            if not pm.isNull():
                icon = QIcon(pm)
    if icon.isNull():
        for size in (16, 32, 48, 64, 128, 256):
            icon.addPixmap(_generated_pixmap(size))
    _cache["icon"] = icon
    return icon


def reload_icon(cfg=None) -> QIcon:
    _cache.clear()
    return app_icon(cfg)


def set_app_user_model_id() -> None:
    """让任务栏把本程序当成独立应用（图标才不会被归到 pythonw 下）。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
    except Exception:  # noqa: BLE001
        pass


def apply_to(app, window=None, cfg=None) -> None:
    icon = app_icon(cfg)
    try:
        app.setWindowIcon(icon)
    except Exception:  # noqa: BLE001
        pass
    if window is not None:
        try:
            window.setWindowIcon(icon)
        except Exception:  # noqa: BLE001
            pass
