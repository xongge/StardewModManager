"""页面基类：统一生命周期钩子，主窗口不再靠 hasattr 探测。"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


class PageBase(QWidget):
    """所有主页面继承它，按需覆盖下面三个钩子。"""

    def on_shown(self) -> None:
        """页面被切到前台时调用。"""

    def refresh(self) -> None:
        """数据层面刷新（扫描结果、版本信息变化等）。"""

    def refresh_theme(self) -> None:
        """配色变化后刷新内联样式。"""

    def shutdown(self) -> None:
        """关闭窗口时停掉页面里还在跑的线程，避免退出崩溃。

        约定：页面把线程存在实例属性上（_worker / _upd_worker / _tr_worker …），
        这里统一做一次 requestInterruption + 短暂等待。
        """
        try:
            from PySide6.QtCore import QThread
        except Exception:  # noqa: BLE001
            return
        for value in list(vars(self).values()):
            if isinstance(value, QThread) and value.isRunning():
                try:
                    value.requestInterruption()
                    stop = getattr(value, "stop", None)
                    if callable(stop):
                        stop()
                    value.wait(1500)
                except Exception:  # noqa: BLE001
                    pass
