"""现代化深色主题 QSS（支持在设置里自定义颜色）。"""
from __future__ import annotations

DEFAULT_COLORS = {
    "bg": "#12161d",
    "bg2": "#171c25",
    "panel": "#1b212c",
    "panel2": "#202836",
    "line": "#2c3542",
    "text": "#d6deeb",
    "muted": "#8895a7",
    "accent": "#4cc38a",
    "accent2": "#2f9e6b",
    "red": "#ff6b6b",
    "yellow": "#ffd166",
    "blue": "#5aa9ff",
    "sys": "#7ee787",
}

# 明亮配色（设置里可一键切换）
LIGHT_COLORS = {
    "bg": "#f4f6f9",
    "bg2": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#eef1f6",
    "line": "#d9dfe8",
    "text": "#1f2733",
    "muted": "#6b7686",
    "accent": "#2b8a5f",
    "accent2": "#1f6f4c",
    "red": "#c0392b",
    "yellow": "#9a6b00",
    "blue": "#2f6fd0",
    "sys": "#1f7a52",
}

# 可在设置里自定义的项：配置键 -> (显示名, 调色板键)
CUSTOMIZABLE = [
    ("theme_accent", "主题强调色", "accent"),
    ("theme_bg", "窗口背景", "bg"),
    ("theme_bg2", "侧栏 / 输入框背景", "bg2"),
    ("theme_panel", "卡片 / 面板", "panel"),
    ("theme_line", "边框线", "line"),
    ("theme_text", "正文文字", "text"),
    ("theme_muted", "次要文字", "muted"),
]

# 供各页面直接引用的当前配色（apply_theme 时会就地更新）
C = dict(DEFAULT_COLORS)


def is_hex(value) -> bool:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        return False
    try:
        int(text[1:], 16)
        return True
    except ValueError:
        return False


def shade(hexcolor: str, factor: float) -> str:
    """把颜色调亮(factor>1)或调暗(factor<1)。"""
    r = int(hexcolor[1:3], 16)
    g = int(hexcolor[3:5], 16)
    b = int(hexcolor[5:7], 16)
    f = lambda v: max(0, min(255, int(round(v * factor))))  # noqa: E731
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


def build_palette(cfg=None) -> dict:
    light = bool(cfg is not None and str(cfg.get("theme_mode") or "") == "light")
    palette = dict(LIGHT_COLORS if light else DEFAULT_COLORS)
    if cfg is not None:
        for key, _label, target in CUSTOMIZABLE:
            value = str(cfg.get(key) or "").strip()
            if is_hex(value):
                palette[target] = value
        if "accent" in palette:
            palette["accent2"] = shade(palette["accent"], 0.72)
        palette["panel2"] = shade(palette["panel"], 1.14)
    return palette


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """按比例混合两个颜色（ratio 是 color_a 的占比）。"""
    try:
        a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
        out = tuple(int(round(a[i] * ratio + b[i] * (1 - ratio))) for i in range(3))
        return "#%02x%02x%02x" % out
    except Exception:  # noqa: BLE001
        return color_b


def is_dark(c: dict) -> bool:
    """粗略判断当前是深色还是明亮配色。"""
    try:
        return int(str(c.get("bg", "#000000"))[1:3], 16) < 128
    except Exception:  # noqa: BLE001
        return True


def badge_bg(c: dict, name: str) -> str:
    """徽章底色：深色主题压暗、明亮主题提亮，保证文字可读。"""
    base = c.get(name, "#888888")
    return shade(base, 0.22) if is_dark(c) else shade(base, 1.86)


def badge_line(c: dict, name: str) -> str:
    base = c.get(name, "#888888")
    return shade(base, 0.55) if is_dark(c) else shade(base, 1.55)


def build_qss(c: dict | None = None) -> str:
    C = dict(c or DEFAULT_COLORS)
    return f"""
* {{ font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 13px; }}
QWidget {{ background: {C['bg']}; color: {C['text']}; }}
QMainWindow, QDialog {{ background: {C['bg']}; }}

#Sidebar {{ background: {C['bg2']}; border-right: 1px solid {C['line']}; }}
#Brand {{ padding: 18px 16px 6px 16px; font-size: 16px; font-weight: 700; color: {C['accent']}; }}
#BrandSub {{ padding: 0 16px 16px 16px; color: {C['muted']}; font-size: 11px; }}

QPushButton#NavBtn {{
    text-align: left; padding: 11px 18px; border: none; border-radius: 9px;
    color: {C['muted']}; background: transparent; font-size: 14px; margin: 3px 10px;
}}
QPushButton#NavBtn:hover {{ color: {C['text']}; }}
QPushButton#NavBtn:checked {{ color: {C['accent']}; font-weight: 700; }}
QWidget#NavPill {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(76,195,138,0.16), stop:1 rgba(76,195,138,0.04));
    border-left: 3px solid {C['accent']};
    border-radius: 9px;
}}

QPushButton {{
    background: {shade(C['panel2'], 1.02 if is_dark(C) else 1.0)};
    border: 1px solid {C['line']}; border-radius: 8px;
    padding: 7px 14px; color: {C['text']};
}}
QPushButton:hover {{ background: {mix(C['accent'], C['panel2'], 0.14)}; border-color: {C['accent']}; }}
QPushButton:pressed {{ background: {shade(C['panel2'], 0.92 if is_dark(C) else 0.9)}; }}
QPushButton:disabled {{ color: {C['muted']}; background: {shade(C['panel2'],0.9)}; border-color: {C['line']}; }}
QPushButton#Primary {{
    background: transparent; border: 1px solid {C['accent']}; color: {C['accent']};
    font-weight: 700; padding: 6px 14px;
}}
QPushButton#Primary:hover {{ background: {mix(C['accent'], C['panel'], 0.18)}; }}
QPushButton#Primary:pressed {{ background: {mix(C['accent'], C['panel'], 0.3)}; }}
QPushButton#Primary:disabled {{ border-color: {C['line']}; color: {C['muted']}; background: transparent; }}
QPushButton#Danger {{
    background: transparent; border: 1px solid {C['red']}; color: {C['red']};
    font-weight: 700; padding: 6px 14px;
}}
QPushButton#Danger:hover {{ background: {mix(C['red'], C['panel'], 0.18)}; }}
QPushButton#Danger:pressed {{ background: {mix(C['red'], C['panel'], 0.3)}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox {{
    background: {C['bg2']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {C['accent2']};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {C['accent2']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {C['panel2']}; border: 1px solid {C['line']}; selection-background-color: {C['accent2']};
}}

QListWidget, QTreeWidget, QTableWidget {{
    background: {C['bg2']}; border: 1px solid {C['line']}; border-radius: 10px; outline: none;
    alternate-background-color: {shade(C['bg2'], 1.06 if is_dark(C) else 0.98)};
}}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {C['panel2']}; color: {C['accent']}; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {shade(C['panel2'], 1.08 if is_dark(C) else 0.96)}; }}
QHeaderView::section {{
    background: {C['panel']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['line']};
    padding: 8px; font-weight: 600;
}}

QGroupBox {{
    border: 1px solid {C['line']}; border-radius: 10px; margin-top: 14px; padding: 14px 12px 10px 12px;
    background: {C['panel']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {C['accent']}; font-weight: 600; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['line']}; background: {C['bg2']}; }}
QCheckBox::indicator:checked {{ background: {C['accent2']}; border-color: {C['accent']}; }}

QProgressBar {{ border: 1px solid {C['line']}; border-radius: 7px; background: {C['bg2']}; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {C['accent2']}; border-radius: 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {shade(C['line'],1.05)}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {shade(C['line'],1.25)}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {shade(C['line'],1.05)}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {C['line']}; }}
QStatusBar {{ background: {C['bg2']}; color: {C['muted']}; border-top: 1px solid {C['line']}; }}
QLabel#Title {{ font-size: 19px; font-weight: 700; }}
QLabel#Sub {{ color: {C['muted']}; }}
QLabel#Hint {{ color: {C['muted']}; font-size: 12px; }}
QLabel#Badge {{ background: {C['panel2']}; border-radius: 9px; padding: 2px 10px; color: {C['muted']}; }}
QLabel#ErrBadge {{ background: transparent; border: none; color: {C['red']}; padding: 2px 4px; font-weight: 700; font-size: 13px; }}
QLabel#WarnBadge {{ background: transparent; border: none; color: {C['yellow']}; padding: 2px 4px; font-weight: 700; font-size: 13px; }}
QLabel#OkBadge {{ background: transparent; border: none; color: {C['accent']}; padding: 2px 4px; font-weight: 700; font-size: 13px; }}
#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {C['panel']}, stop:1 {shade(C['panel'], 0.86)});
    border: 1px solid {C['line']}; border-radius: 10px;
}}
QGroupBox {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {C['panel']}, stop:1 {shade(C['panel'], 0.86)});
}}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['line']}; padding: 4px; }}
QStatusBar::item {{ border: none; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


# 兼容旧引用：默认主题
QSS = build_qss(DEFAULT_COLORS)


def apply_theme(app, cfg=None) -> dict:
    """按配置重建配色并应用到整个应用；返回新的调色板。"""
    palette = build_palette(cfg)
    C.clear()
    C.update(palette)
    try:
        app.setStyleSheet(build_qss(palette))
    except Exception:  # noqa: BLE001
        pass
    return palette


def apply_shadow(widget, blur: int = 24, dy: int = 6, alpha: int = 110) -> None:
    """给卡片/面板加柔和阴影，让界面更有层次。"""
    try:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(0, dy)
        effect.setColor(QColor(0, 0, 0, alpha))
        widget.setGraphicsEffect(effect)
    except Exception:  # noqa: BLE001
        pass


MONO = '"Cascadia Mono", "Consolas", "JetBrains Mono", monospace'


def enable_dark_titlebar(widget, dark: bool = True) -> bool:
    """把 Windows 原生标题栏变成深色（Win10 1809+ / Win11）。"""
    try:
        import ctypes
        from ctypes import wintypes

        widget.winId()  # 确保句柄已创建
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE（旧版本是 19）
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(attr), ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        # 标题栏/边框颜色跟随主题（Win11）
        def _color(attr: int, hexcolor: str) -> None:
            r = int(hexcolor[1:3], 16)
            g = int(hexcolor[3:5], 16)
            b = int(hexcolor[5:7], 16)
            # COLORREF 是 0x00BBGGRR
            ref = ctypes.c_uint(r | (g << 8) | (b << 16))
            try:
                dwm.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), ctypes.c_uint(attr), ctypes.byref(ref), ctypes.sizeof(ref)
                )
            except Exception:  # noqa: BLE001
                pass

        _color(35, C["bg2"] if dark else C["bg"])   # DWMWA_CAPTION_COLOR
        _color(34, C["line"])  # DWMWA_BORDER_COLOR
        _color(36, C["text"])  # DWMWA_TEXT_COLOR
        if not dark:
            _color(34, C["line"])
        return True
    except Exception:  # noqa: BLE001
        return False
