"""软件更新提示：后台检查 + 一键安装（自动下载、静默覆盖安装、自动重启）。

更新窗口只有两个按钮：「一键安装」和「取消」。
点安装后：应用内下载新版本安装包 → 退出程序 → 后台脚本静默安装到当前目录 → 重新启动。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import APP_NAME, APP_VERSION
from .. import selfupdate as su
from ..config import cache_path
from .theme import C

APP_FOLDER = "StardewModManager"
EXE_NAME = "StardewModManager.exe"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

APPLY_SCRIPT = r"""@echo off
setlocal
set "SETUP=%~1"
set "TARGET=%~2"
set "APP=%~3"
set "PID=%~4"
:wait
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
if exist "%SETUP%" "%SETUP%" --silent "%TARGET%" --no-launch --no-shortcuts
if exist "%APP%" start "" "%APP%"
del /f /q "%SETUP%" >nul 2>nul
exit /b
"""


def install_root() -> Path:
    """程序所在的安装根目录（安装包会把 StardewModManager\\ 放进去）。"""
    exe_dir = Path(sys.executable).resolve().parent
    if exe_dir.name.lower() == APP_FOLDER.lower():
        return exe_dir.parent
    return exe_dir


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False)) and (install_root() / APP_FOLDER).exists()


def launch_apply_script(setup_path: Path) -> tuple[bool, str]:
    """退出后由批处理等待进程结束 → 静默安装 → 重新启动。"""
    try:
        root = install_root()
        target = Path(sys.executable).resolve()
        script = setup_path.parent / "apply_update.cmd"
        script.write_text(APPLY_SCRIPT, encoding="ascii")
        subprocess.Popen(
            ["cmd.exe", "/c", str(script), str(setup_path), str(root), str(target), str(os.getpid())],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
            cwd=str(setup_path.parent),
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


class SelfUpdateWorker(QThread):
    """后台查 GitHub Release。"""

    done = Signal(object, str)

    def __init__(self, repo: str, current: str, force: bool = True, use_cache: bool = False, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.current = current
        self.force = force
        self.use_cache = use_cache

    def run(self) -> None:  # noqa: D102
        try:
            cache = su.AppUpdateCache(cache_path("app_update.json"))
            result = su.check(self.current, self.repo, cache,
                              force=self.force or not self.use_cache)
            self.done.emit(result, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))


class DownloadWorker(QThread):
    """下载新版本安装包。"""

    progress = Signal(int)
    done = Signal(bool, str, str)   # ok, 文件路径, 错误

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102
        try:
            url = self.info.get("installer_url") or ""
            if not url:
                self.done.emit(False, "", "这个版本没有可下载的安装包，请到发布页手动下载")
                return
            ver = str(self.info.get("latest") or "new").replace("/", "_")
            dest = cache_path("update") / f"setup-{ver}.exe"
            self.progress.emit(1)
            su.download_asset(
                url, dest,
                progress=lambda p: self.progress.emit(int(p * 100)),
                should_stop=lambda: self._stop,
            )
            self.progress.emit(100)
            self.done.emit(True, str(dest), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, "", str(exc))


class UpdateDialog(QDialog):
    """更新窗口：只有「一键安装」和「取消」两个按钮。"""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self._worker = None
        self._installing = False
        self.setWindowTitle("发现新版本")
        self.resize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel(f"{APP_NAME}　{info.get('current')} → {info.get('latest')}")
        title.setObjectName("Title")
        root.addWidget(title)

        sub = QLabel(
            f"发布于 {info.get('published') or '-'}　·　仓库 {info.get('repo')}"
            + ("　（结果来自本地缓存）" if info.get("from_cache") else "")
        )
        sub.setObjectName("Hint")
        root.addWidget(sub)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        text = (info.get("notes") or "（这次 Release 没有写更新说明）")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r"^###?\s*(.+)$", r"<b>\1</b>", text, flags=re.M).replace("\n", "<br>")
        body.setHtml(f'<div style="color:{C["text"]};line-height:1.55;">{text}</div>')
        root.addWidget(body, 1)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.bar.setRange(0, 100)
        root.addWidget(self.bar)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setVisible(False)
        root.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.install_btn = QPushButton("一键安装")
        self.install_btn.setObjectName("Primary")
        self.install_btn.clicked.connect(self.start_install)
        row.addWidget(self.install_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        root.addLayout(row)

    # ---------------- 一键安装
    def start_install(self) -> None:
        if self._installing:
            return
        if not can_self_update():
            QMessageBox.information(
                self, "无法自动安装",
                "当前是源码运行模式，自动安装只对安装版有效。\n\n"
                "请到发布页手动下载安装包。",
            )
            return
        self._installing = True
        self.install_btn.setEnabled(False)
        self.install_btn.setText("下载中…")
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.status.setVisible(True)
        self.status.setText("正在下载新版本安装包…")

        worker = DownloadWorker(self.info, self)
        worker.progress.connect(self.bar.setValue)
        worker.done.connect(self._on_downloaded)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_downloaded(self, ok: bool, path: str, err: str) -> None:
        if not ok:
            self._installing = False
            self.bar.setVisible(False)
            self.status.setText("下载失败：" + err)
            self.install_btn.setEnabled(True)
            self.install_btn.setText("一键安装")
            self.cancel_btn.setEnabled(True)
            return
        self.status.setText("下载完成，正在安装并重启…")
        self.install_btn.setText("安装中…")
        started, msg = launch_apply_script(Path(path))
        if not started:
            self._installing = False
            self.install_btn.setEnabled(True)
            self.install_btn.setText("一键安装")
            self.cancel_btn.setEnabled(True)
            self.status.setText("启动安装失败：" + msg)
            return
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()

    def reject(self) -> None:  # noqa: D102
        if self._installing:
            return   # 安装过程中不允许取消/关闭
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._installing:
            event.ignore()
            return
        super().closeEvent(event)


def notify_if_any(window, ctx, force: bool = False) -> None:
    """检查并提示（启动时静默检查一次）。"""
    repo = str(ctx.config.get("app_repo") or su.DEFAULT_REPO)
    worker = SelfUpdateWorker(repo, APP_VERSION, force=force, use_cache=not force, parent=window)
    window._selfupdate_worker = worker

    def on_done(info, err):
        if err:
            if force:
                QMessageBox.information(window, "检查更新失败", str(err))
            return
        if not info:
            return
        import time as _time

        ctx.config.set("last_app_check", _time.time())
        ctx.config.save()
        if info.get("has_update"):
            window.set_update_hint(info)
            if force or str(ctx.config.get("dismissed_version") or "") != str(info.get("latest")):
                dlg = UpdateDialog(info, window)
                dlg.exec()
        elif force:
            QMessageBox.information(
                window, "已是最新",
                f"当前版本 {APP_VERSION} 已是最新版本（{info.get('latest')}）。",
            )

    worker.done.connect(on_done)
    worker.finished.connect(worker.deleteLater)
    worker.start()
