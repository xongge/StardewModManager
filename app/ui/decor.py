"""状态小装饰：呼吸圆点（表示正在运行 / 正在检查）。

只保留“状态提示”类的动效，页面背景不加任何动画。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import anim

GREEN = (76, 195, 138)
BLUE = (90, 169, 255)
GOLD = (255, 209, 102)


class PulseDot(QWidget):
    """会呼吸的小圆点：运行时闪烁，静止时是暗点。"""

    def __init__(self, parent: QWidget, color=GREEN, size: int = 12, cfg=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(size, size)
        self._color = color
        self._phase = 0.0
        self._running = False
        self._on = anim.enabled(cfg)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._step)
        if self._on:
            self._timer.start()

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self.update()

    def set_color(self, color) -> None:
        self._color = color
        self.update()

    def set_enabled(self, flag: bool, cfg=None) -> None:
        self._on = bool(flag) and anim.enabled(cfg)
        if self._on:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _step(self) -> None:
        if not self.isVisible() or not self._running:
            return
        self._phase += 0.12
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            r, g, b = self._color
            w = self.width()
            cx = cy = w / 2.0
            if self._running and self._on:
                t = (math.sin(self._phase) + 1) / 2.0
                halo = w * (0.55 + 0.35 * t)
                grad = QRadialGradient(QPointF(cx, cy), halo)
                grad.setColorAt(0.0, QColor(r, g, b, int(70 + 60 * t)))
                grad.setColorAt(1.0, QColor(r, g, b, 0))
                p.setBrush(QBrush(grad))
                p.drawEllipse(QPointF(cx, cy), halo, halo)
                core = w * 0.26
            else:
                core = w * 0.22
            p.setBrush(QColor(r, g, b, 235 if self._running else 120))
            p.drawEllipse(QPointF(cx, cy), core, core)
            p.end()
        except Exception:  # noqa: BLE001
            pass
