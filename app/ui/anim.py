"""轻量动画辅助：淡入、页面切换、徽标脉冲、提示条滑出、导航高亮块。

全部做了异常保护，动画出问题也不影响功能。
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsOpacityEffect,
    QWidget,
)

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


def switch_page(stack, index: int, ms: int = 300, direction: int = 1) -> None:
    """页面切换：旧页面快照轻轻滑走并淡出，新页面同时淡入（十字过渡）。

    direction：1 表示往右翻页，-1 表示往左翻页，旧页面朝相反方向滑出。
    """
    try:
        if stack.currentIndex() == index:
            return
        if not enabled():
            stack.setCurrentIndex(index)
            return
        old = stack.currentWidget()
        pix = old.grab() if old is not None else None
        stack.setCurrentIndex(index)
        new = stack.currentWidget()
        if new is None or pix is None or pix.isNull():
            fade_in(new, ms)
            return

        overlay = getattr(stack, "_page_overlay", None)
        if overlay is None:
            from PySide6.QtWidgets import QLabel

            overlay = QLabel(stack)
            overlay.setObjectName("PageOverlay")
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            stack._page_overlay = overlay
        overlay.setPixmap(pix)
        w, h = max(1, stack.width()), max(1, stack.height())
        overlay.setGeometry(0, 0, w, h)
        overlay.show()
        overlay.raise_()

        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        group = QParallelAnimationGroup(overlay)

        geo = QPropertyAnimation(overlay, b"pos", overlay)
        geo.setStartValue(QPoint(0, 0))
        geo.setEndValue(QPoint(int(-direction * w * 0.16), 0))
        geo.setDuration(ms)
        geo.setEasingCurve(QEasingCurve.OutCubic)
        fade = QPropertyAnimation(effect, b"opacity", overlay)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setDuration(ms)
        fade.setEasingCurve(QEasingCurve.OutQuad)
        group.addAnimation(geo)
        group.addAnimation(fade)

        def done():
            try:
                overlay.hide()
                overlay.setPixmap(QPixmap())
                overlay.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass

        group.finished.connect(done)
        stack._page_anim = group
        group.start()
        fade_in(new, ms)
    except Exception:  # noqa: BLE001
        try:
            stack.setCurrentIndex(index)
        except Exception:  # noqa: BLE001
            pass


class HoverHighlight(QWidget):
    """跟随鼠标的“滑动高亮条”，给条目列表做出过渡感。

    用法：HoverHighlight(self.tree) / HoverHighlight(self.cats)
    —— 鼠标在同列相邻条目间移动时，高亮块会平滑滑过去，而不是瞬间跳。
    """

    def __init__(self, view, radius: int = 7, parent: QWidget | None = None):
        super().__init__(parent or view.viewport())
        self._view = view
        self._radius = radius
        self._item = None
        self._geo_anim = None
        self._fade_anim = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.ArrowCursor)
        self.hide()
        try:
            view.viewport().setMouseTracking(True)
            view.viewport().installEventFilter(self)
            view.verticalScrollBar().valueChanged.connect(self._resync)
            view.horizontalScrollBar().valueChanged.connect(self._resync)
        except Exception:  # noqa: BLE001
            pass

    # ---- 绘制
    def paintEvent(self, _event) -> None:  # noqa: N802
        try:
            from PySide6.QtGui import QColor, QPainter

            from .theme import C

            color = QColor(C.get("accent", "#4cc38a"))
            color.setAlpha(30)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self._radius, self._radius)
        except Exception:  # noqa: BLE001
            pass

    # ---- 事件
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        try:
            kind = event.type()
            if kind == QEvent.MouseMove:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._hover_at(pos)
            elif kind in (QEvent.Leave, QEvent.Hide):
                self._leave()
            elif kind == QEvent.Wheel:
                QTimer.singleShot(0, self._resync)
        except Exception:  # noqa: BLE001
            pass
        return False

    # ---- 内部
    def _rect_for(self, item):
        try:
            rect = self._view.visualItemRect(item)
        except Exception:  # noqa: BLE001
            return None
        if rect is None or rect.height() <= 0:
            return None
        width = self._view.viewport().width()
        return QRect(2, rect.top() + 1, max(8, width - 5), max(6, rect.height() - 2))

    def _hover_at(self, pos) -> None:
        try:
            item = self._view.itemAt(pos)
        except Exception:  # noqa: BLE001
            item = None
        if item is None:
            self._leave()
            return
        rect = self._rect_for(item)
        if rect is None:
            self._leave()
            return
        if item is self._item and self.isVisible():
            if self.geometry() != rect:
                self.setGeometry(rect)
            return
        self._item = item
        if not self.isVisible() or self.height() <= 0:
            self.setGeometry(rect)
            self.show()
            self.raise_()
            self._animate_opacity(0.0, 1.0, 130)
        else:
            self._animate_geometry(rect, 120)

    def _leave(self) -> None:
        self._item = None
        if not self.isVisible():
            return
        self._animate_opacity(1.0, 0.0, 130, hide_after=True)

    def _resync(self) -> None:
        if self._item is None:
            return
        rect = self._rect_for(self._item)
        if rect is None:
            self._leave()
        else:
            self.setGeometry(rect)

    def _animate_geometry(self, rect, ms: int) -> None:
        if not enabled():
            self.setGeometry(rect)
            return
        try:
            anim = QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(ms)
            anim.setStartValue(self.geometry())
            anim.setEndValue(rect)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._geo_anim = anim
            anim.start()
        except Exception:  # noqa: BLE001
            self.setGeometry(rect)

    def _animate_opacity(self, start: float, end: float, ms: int, hide_after: bool = False) -> None:
        if not enabled() or ms <= 1:
            try:
                self.setWindowOpacity(1.0)
            except Exception:  # noqa: BLE001
                pass
            if hide_after:
                self.hide()
            return
        try:
            effect = self.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(self)
                self.setGraphicsEffect(effect)
            effect.setOpacity(start)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(ms)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def done():
                if hide_after:
                    self.hide()
                    self.setGraphicsEffect(None)

            anim.finished.connect(done)
            self._fade_anim = anim
            anim.start()
        except Exception:  # noqa: BLE001
            if hide_after:
                self.hide()


class HoverTint(QWidget):
    """按钮悬停时的淡淡色层（淡入淡出，避免瞬间变色）。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._fade = None
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

    def paintEvent(self, _event) -> None:  # noqa: N802
        try:
            from PySide6.QtGui import QColor, QPainter

            from .theme import C

            name = self.parent().objectName() if self.parent() else ""
            base = C.get("red") if name == "Danger" else C.get("accent", "#4cc38a")
            color = QColor(base)
            color.setAlpha(26 if name == "Danger" else 20)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 7, 7)
        except Exception:  # noqa: BLE001
            pass

    def fade(self, start: float, end: float, ms: int) -> None:
        try:
            if not enabled() or ms <= 1:
                self._effect.setOpacity(end)
                if end <= 0.01:
                    self.hide()
                return
            anim = QPropertyAnimation(self._effect, b"opacity", self)
            anim.setDuration(ms)
            anim.setStartValue(float(start))
            anim.setEndValue(float(end))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: self.hide() if end <= 0.01 else None)
            self._fade = anim
            anim.start()
        except Exception:  # noqa: BLE001
            pass


class SoftPress(QObject):
    """全局按钮反馈：按下时轻微压暗再回弹，点哪里都有手感。"""

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        try:
            app.installEventFilter(self)
        except Exception:  # noqa: BLE001
            pass

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        try:
            kind = event.type()
            if isinstance(obj, QAbstractButton):
                if kind == QEvent.MouseButtonPress:
                    self._flash(obj)
                elif kind == QEvent.Enter:
                    self._hover(obj, True)
                elif kind == QEvent.Leave:
                    self._hover(obj, False)
                elif kind == QEvent.Resize:
                    self._resize_tint(obj)
        except Exception:  # noqa: BLE001
            pass
        return False

    # ---- 悬停淡淡上色
    @staticmethod
    def _hover(widget, on: bool) -> None:
        if not enabled():
            return
        try:
            tint = getattr(widget, "_hover_tint", None)
            if tint is None:
                if not on:
                    return
                tint = HoverTint(widget)
                widget._hover_tint = tint
                tint.show()
                tint.setGeometry(widget.rect())
                tint.fade(0.0, 1.0, 130)
                return
            tint.setGeometry(widget.rect())
            tint.fade(0.0 if not on else 1.0, 1.0 if on else 0.0, 150)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _resize_tint(widget) -> None:
        try:
            tint = getattr(widget, "_hover_tint", None)
            if tint is not None:
                tint.setGeometry(widget.rect())
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _flash(widget) -> None:
        if not enabled():
            return
        try:
            if widget.graphicsEffect() is not None:
                return
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(170)
            anim.setKeyValueAt(0.0, 1.0)
            anim.setKeyValueAt(0.28, 0.7)
            anim.setKeyValueAt(1.0, 1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: widget.setGraphicsEffect(None))
            widget._press_anim = anim
            anim.start()
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
