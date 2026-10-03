"""软件更新提示：后台检查 + 一个展示更新内容的小窗口。"""
from __future__ import annotations

import re
import webbrowser

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import APP_NAME, APP_VERSION
from .. import selfupdate as su
from ..config import cache_path
from .theme import C


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


class UpdateDialog(QDialog):
    """展示新版本信息，提供打开发布页 / 下载安装包。"""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("发现新版本")
        self.resize(660, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel(f"{APP_NAME}　{info.get('current')} → {info.get('latest')}")
        title.setObjectName("Title")
        root.addWidget(title)

        sub = QLabel(
            f"发布于 {info.get('published') or '-'}　·　"
            f"仓库 {info.get('repo')}"
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

        row = QHBoxLayout()
        page_btn = QPushButton("打开发布页")
        page_btn.setObjectName("Primary")
        page_btn.clicked.connect(self._open_page)
        row.addWidget(page_btn)
        if info.get("installer_url"):
            dl = QPushButton("下载最新安装包")
            dl.clicked.connect(self._download)
            row.addWidget(dl)
        row.addStretch(1)
        later = QPushButton("稍后再说")
        later.clicked.connect(self.reject)
        row.addWidget(later)
        root.addLayout(row)

    def _open_page(self) -> None:
        if self.info.get("page"):
            webbrowser.open(self.info["page"])

    def _download(self) -> None:
        url = self.info.get("installer_url") or self.info.get("page")
        if url:
            webbrowser.open(url)


def notify_if_any(window, ctx, force: bool = False) -> None:
    """检查并提示（启动时静默检查一次）。"""
    repo = str(ctx.config.get("app_repo") or su.DEFAULT_REPO)
    worker = SelfUpdateWorker(repo, APP_VERSION, force=force, use_cache=not force, parent=window)
    window._selfupdate_worker = worker

    def on_done(info, err):
        if err:
            if force:
                from PySide6.QtWidgets import QMessageBox

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
                if dlg.result() != QDialog.Accepted:
                    ctx.config.set("dismissed_version", info.get("latest"))
                    ctx.config.save()
        elif force:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                window, "已是最新",
                f"当前版本 {APP_VERSION} 已是最新版本（{info.get('latest')}）。",
            )

    worker.done.connect(on_done)
    worker.finished.connect(worker.deleteLater)
    worker.start()
