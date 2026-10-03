"""轻量动画辅助：淡入、页面切换、徽标脉冲、提示条滑出、导航高亮块。

全部做了异常保护，动画出问题也不影响功能。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

ENABLED = True


def enabled(cfg=None) -> bool:
    if not ENABLED:
        return False
    if cfg is not None:
        return bool(cfg.get("animations", True))
    return True


def fade_in(widget: QWidget, ms: int = 320, keep: bool = False) -> None:
    """淡入（OutQuint 曲线，比原来柔和）。keep=False 时结束后移除特效。"""
    if widget is None:
        return
    try:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutQuint)

        def done():
            if not keep:
                try:
                    widget.setGraphicsEffect(None)
                except Exception:  # noqa: BLE001
                    pass

        anim.finished.connect(done)
        widget._fade_anim = anim  # type: ignore[attr-defined]
        anim.start()
    except Exception:  # noqa: BLE001
        pass


def pulse(widget: QWidget, ms: int = 260) -> None:
    """轻微脉冲（用于错误/警告数字变化时提醒）。"""
    if widget is None:
        return
    try:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(ms)
        anim.setKeyValueAt(0.0, 1.0)
        anim.setKeyValueAt(0.4, 0.35)
        anim.setKeyValueAt(1.0, 1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        widget._pulse_anim = anim  # type: ignore[attr-defined]
        anim.start()
    except Exception:  # noqa: BLE001
        pass


def slide_down_show(widget: QWidget, ms: int = 200) -> None:
    """提示条出现：高度由 0 展开 + 淡入。"""
    if widget is None:
        return
    widget.setVisible(True)
    try:
        target = widget.sizeHint().height()
        anim = QPropertyAnimation(widget, b"maximumHeight", widget)
        anim.setDuration(ms)
        anim.setStartValue(0)
        anim.setEndValue(max(target, widget.height()))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
        widget._slide_anim = anim  # type: ignore[attr-defined]
        anim.start()
        fade_in(widget, ms)
    except Exception:  # noqa: BLE001
        pass


def switch_page(stack, index: int, ms: int = 200) -> None:
    """切换 QStackedWidget 页面并淡入新页面。"""
    try:
        if stack.currentIndex() == index:
            return
        stack.setCurrentIndex(index)
        fade_in(stack.currentWidget(), ms)
    except Exception:  # noqa: BLE001
        try:
            stack.setCurrentIndex(index)
        except Exception:  # noqa: BLE001
            pass


class NavPill(QWidget):
    """导航栏里会滑动的高亮块。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("NavPill")
        try:
            from PySide6.QtCore import Qt

            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:  # noqa: BLE001
            pass
        self._anim = None
        self.hide()

    def move_to(self, geometry, animate: bool = True, ms: int = 260) -> None:
        if geometry is None:
            self.hide()
            return
        self.show()
        self.raise_()
        try:
            if animate and enabled():
                anim = QPropertyAnimation(self, b"geometry", self)
                anim.setDuration(ms)
                anim.setStartValue(self.geometry())
                anim.setEndValue(geometry)
                anim.setEasingCurve(QEasingCurve.OutQuart)
                self._anim = anim
                anim.start()
            else:
                self.setGeometry(geometry)
        except Exception:  # noqa: BLE001
            self.setGeometry(geometry)
