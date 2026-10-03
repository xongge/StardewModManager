"""主窗口：左侧导航 + 分类页面（类似 WeGame / 游戏启动器布局）。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_VERSION
from ..context import AppContext
from . import anim, icon as iconlib
from . import theme as themelib
from .pages.console_page import ConsolePage
from .pages.mods_page import ModsPage
from .pages.settings_page import SettingsPage
from .pages.updater_page import UpdaterPage
from .theme import C, enable_dark_titlebar

NAV = [
    ("🧩  模组管理", "分类浏览、启用 / 停用 Mod"),
    ("🖥  运行控制台", "应用内控制台，替代 CMD 黑窗"),
    ("⬆  SMAPI 更新", "检查并安装 / 修复 SMAPI"),
    ("⚙  设置", "游戏目录 / Mod 文件夹 / AI 汉化"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ctx = AppContext(self)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 660)
        iconlib.apply_to(QApplication.instance(), self, self.ctx.config)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------- 侧边栏
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        self.side = side
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.setSpacing(4)
        brand = QLabel("星露谷 Mod 管理器")
        brand.setObjectName("Brand")
        sub = QLabel("Stardew Valley Mod Manager")
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)

        self.pill = anim.NavPill(side)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.nav_buttons = []
        for i, (text, tip) in enumerate(NAV):
            btn = QPushButton(text)
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            self.group.addButton(btn, i)
            sl.addWidget(btn)
            self.nav_buttons.append(btn)
        sl.addStretch(1)

        self.theme_btn = QPushButton("🌙  深色")
        self.theme_btn.setObjectName("NavBtn")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("一键切换深色 / 明亮配色（顶部标题栏也会一起换）")
        self.theme_btn.clicked.connect(self.toggle_theme_mode)
        self._sync_theme_btn()
        sl.addWidget(self.theme_btn)
        sl.addSpacing(6)

        self.counts = QLabel("扫描中…")
        self.counts.setObjectName("Hint")
        self.counts.setWordWrap(True)
        self.counts.setContentsMargins(16, 0, 12, 0)
        sl.addWidget(self.counts)
        root.addWidget(side)

        # ---------------- 页面
        self.stack = QStackedWidget()
        self.mods_page = ModsPage(self.ctx)
        self.console_page = ConsolePage(self.ctx)
        self.updater_page = UpdaterPage(self.ctx, on_run=self._run_in_console)
        self.settings_page = SettingsPage(self.ctx, on_saved=self._after_save)
        for page in (self.mods_page, self.console_page, self.updater_page, self.settings_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_label = QLabel("就绪")
        bar.addWidget(self.status_label, 1)
        self.update_btn = QPushButton(f"v{APP_VERSION} · 检查软件更新")
        self.update_btn.setObjectName("Hint")
        self.update_btn.setFlat(True)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setToolTip("从 GitHub Releases 检查是否有新版本")
        self.update_btn.clicked.connect(self.check_app_update)
        bar.addPermanentWidget(self.update_btn)

        self.group.idClicked.connect(self.goto_page)
        self.group.button(0).setChecked(True)
        self.ctx.status.connect(self.status_label.setText)
        self.ctx.modsChanged.connect(self._refresh_counts)
        self.ctx.smapiInfoChanged.connect(self._refresh_counts)
        self.console_page.repairRequested.connect(self.repair_smapi)

        self.ctx.update_smapi_installed()
        self.ctx.refresh_mods()

        # 游戏目录自检：自动纠正“只有 SMAPI 残留、没有游戏本体”的错误目录
        fix_msg = self.ctx.fix_game_dir_if_needed()
        if fix_msg:
            self.status_label.setText(fix_msg)
            self.console_page.show_warning(
                fix_msg + "\n\n如果不对，请到「设置」页面手动选择包含 Stardew Valley.exe 的目录。"
            )

        # 快捷键
        for seq, idx in (("F5", 1), ("Ctrl+1", 0), ("Ctrl+2", 1), ("Ctrl+3", 2), ("Ctrl+4", 3)):
            sc = QShortcut(QKeySequence(seq), self)
            if seq == "F5":
                sc.activated.connect(
                    lambda: (
                        self.goto_page(1),
                        self.console_page.launch_game(),
                    )
                )
            else:
                sc.activated.connect(lambda i=idx: self.goto_page(i))

        if self.ctx.config.get("auto_check_smapi") and self.ctx.game_dir:
            self.updater_page.check()
        QTimer.singleShot(2500, self.silent_app_update_check)

    # ---------------- 页面切换（带滑动高亮块 + 淡入）
    def goto_page(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        self.group.button(index).setChecked(True)
        anim.switch_page(self.stack, index)
        self._move_pill(animate=True)
        widget = self.stack.currentWidget()
        if hasattr(widget, "on_shown"):
            try:
                widget.on_shown()
            except Exception:  # noqa: BLE001
                pass

    def _move_pill(self, animate: bool = True) -> None:
        try:
            idx = self.stack.currentIndex()
            btn = self.nav_buttons[idx]
            geo = btn.geometry()
            self.pill.move_to(geo.adjusted(6, 3, -6, -3), animate)
        except Exception:  # noqa: BLE001
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._move_pill(animate=False)
        if not getattr(self, "_pill_ready", False):
            self._pill_ready = True
            self._move_pill(animate=False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            enable_dark_titlebar(self, dark=str(self.ctx.config.get('theme_mode') or 'dark') != 'light')
            iconlib.apply_to(QApplication.instance(), self, self.ctx.config)
            anim.fade_in(self.centralWidget(), 260)
            anim.fade_in(self.pill, 400, keep=False)
        self._move_pill(animate=False)

    def repair_smapi(self) -> None:
        """诊断提示条上的「一键安装 / 修复 SMAPI」。"""
        self.goto_page(2)
        self.updater_page.download_and_install(auto=True, force=True)

    # ---------------- 槽
    def _run_in_console(self, program: str, args, cwd: str, label: str) -> None:
        self.goto_page(1)
        self.console_page.start_process(program, args, cwd, label)

    def _after_save(self) -> None:
        self.ctx.update_smapi_installed()
        self.ctx.refresh_mods()
        self.updater_page.refresh_installed()
        themelib.apply_theme(QApplication.instance(), self.ctx.config)
        self.refresh_theme()
        self.apply_titlebar_mode()
        iconlib.reload_icon(self.ctx.config)
        iconlib.apply_to(QApplication.instance(), self, self.ctx.config)
        value = bool(self.ctx.config.get("animations", True))
        try:
            self.console_page.dot.set_enabled(value, self.ctx.config)
        except Exception:  # noqa: BLE001
            pass

    def _sync_theme_btn(self) -> None:
        light = str(self.ctx.config.get("theme_mode") or "dark") == "light"
        self.theme_btn.setText("☀  明亮" if light else "🌙  深色")

    def toggle_theme_mode(self) -> None:
        """深色 / 明亮一键切换（放在侧栏，随时能点）。"""
        light = str(self.ctx.config.get("theme_mode") or "dark") == "light"
        self.ctx.config.set("theme_mode", "dark" if light else "light")
        self.ctx.config.save()
        themelib.apply_theme(QApplication.instance(), self.ctx.config)
        self.refresh_theme()
        self.apply_titlebar_mode()
        self._sync_theme_btn()
        self.settings_page.refresh_colors()
        self.ctx.status.emit("已切换到" + ("明亮配色" if not light else "深色配色"))

    def set_update_hint(self, info: dict) -> None:
        """状态栏提示有新版本。"""
        try:
            self.update_btn.setText(f"↓ 有新版本 {info.get('latest')}（当前 {APP_VERSION}）")
            self.update_btn.setStyleSheet(f"color:{C['accent']};font-weight:700;")
            self.ctx.status.emit(f"发现新版本 {info.get('latest')}，点右下角查看")
        except Exception:  # noqa: BLE001
            pass

    def check_app_update(self) -> None:
        from .dialog_update import notify_if_any

        notify_if_any(self, self.ctx, force=True)

    def silent_app_update_check(self) -> None:
        if not self.ctx.config.get("auto_check_app_update", True):
            return
        import time

        last = 0.0
        try:
            last = float(self.ctx.config.get("last_app_check") or 0) if str(
                self.ctx.config.get("last_app_check") or "").replace(".", "").isdigit() else 0.0
        except Exception:  # noqa: BLE001
            last = 0.0
        if time.time() - last < 12 * 3600:
            return
        from .dialog_update import notify_if_any

        notify_if_any(self, self.ctx, force=False)

    def apply_titlebar_mode(self) -> None:
        """标题栏跟随深色 / 明亮主题（切换配色时也要重新应用）。"""
        mode = str(self.ctx.config.get("theme_mode") or "dark")
        enable_dark_titlebar(self, dark=mode != "light")

    def refresh_theme(self) -> None:
        """配色变化后让各页刷新内联样式（控制台底色、提示条等）。"""
        for page in (self.mods_page, self.console_page, self.updater_page, self.settings_page):
            hook = getattr(page, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except Exception:  # noqa: BLE001
                    pass

    def _refresh_counts(self) -> None:
        s = self.ctx.stats()
        self.counts.setText(
            f"Mod {s['total']} 个\n启用 {s['enabled']} · 停用 {s['disabled']}\n"
            f"错误 {s['errors']} · 警告 {s['warnings']}\n"
            f"SMAPI {self.ctx.smapi_installed or '未检测到'}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.ctx.runner.running:
            r = QMessageBox.question(
                self, "游戏仍在运行", "游戏进程还在运行，要停止它并退出管理器吗？"
            )
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.ctx.runner.stop()
        self.ctx.shutdown()
        event.accept()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    iconlib.set_app_user_model_id()
    win = MainWindow()
    themelib.apply_theme(app, win.ctx.config)
    win.refresh_theme()
    iconlib.apply_to(app, win, win.ctx.config)
    win.show()
    return app.exec()
