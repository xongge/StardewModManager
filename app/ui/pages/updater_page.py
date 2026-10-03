"""SMAPI 更新页：检查 / 下载 / 一键安装与修复。"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import smapi
from ...config import config_dir
from ..theme import C


def _v(text: str):
    return tuple(int(x) for x in re.findall(r"\d+", str(text or ""))[:4])


def _cmp_ge(installed: str, latest: str) -> bool:
    """installed >= latest（补零比较，6.6 与 6.6.0 视为相同）。"""
    a, b = _v(installed), _v(latest)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))


class TranslateWorker(QThread):
    """把 SMAPI 更新日志发给 AI 翻译。"""

    done = Signal(str, str, str)   # 译文, 使用的模型, 错误

    def __init__(self, text, base, key, model, fallbacks=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.base = base
        self.key = key
        self.model = model
        self.fallbacks = fallbacks or []

    def run(self) -> None:  # noqa: D102
        try:
            from ... import ai as ailab

            out, used = ailab.translate_text(
                self.text, self.base, self.key, self.model, fallbacks=self.fallbacks
            )
            self.done.emit(out, used, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", "", str(exc))


class CheckWorker(QThread):
    done = Signal(object, str)

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(smapi.latest_release(), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))


class InstallWorker(QThread):
    """下载安装包并（可选）直接安装到游戏目录。"""

    progress = Signal(int, int)
    message = Signal(str)
    done = Signal(str, str)

    def __init__(self, url: str, version: str, game_dir: str, auto_install: bool, parent=None):
        super().__init__(parent)
        self.url = url
        self.version = version
        self.game_dir = game_dir
        self.auto = auto_install

    def run(self) -> None:  # noqa: D102
        try:
            base = config_dir() / "smapi_update"
            base.mkdir(parents=True, exist_ok=True)
            target = base / f"SMAPI-{self.version}"
            payload = smapi.find_payload(smapi.find_package_root(target)) if target.exists() else None
            if payload is None:
                zip_path = base / f"SMAPI-{self.version}-installer.zip"
                self.message.emit(f"[更新] 正在下载 {self.url.rsplit('/', 1)[-1]} …")
                smapi.download(
                    self.url, zip_path, lambda got, total: self.progress.emit(got, total)
                )
                self.message.emit("[更新] 下载完成，正在解压…")
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                smapi.extract(zip_path, target)
            else:
                self.message.emit("[更新] 使用已下载的安装包。")

            if not self.auto:
                self.done.emit(str(target), "")
                return

            root = smapi.find_package_root(target)
            backup = config_dir() / "backup" / f"smapi_{self.version}"
            info = smapi.install_from_package(root, self.game_dir, backup, log=self.message.emit)
            state = info["verify"]
            if state["ok"]:
                self.done.emit(str(target), "")
            else:
                self.done.emit(
                    str(target), "安装后仍缺少：" + "、".join(state["missing"])
                )
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", str(exc))


class UpdaterPage(QWidget):
    def __init__(self, ctx, on_run=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_run = on_run
        self._worker = None
        self._dl = None
        self._tr_worker = None
        self._notes_cache: dict = {}
        self._cache_path = config_dir() / "release_notes_cache.json"
        self._load_notes_cache()

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("SMAPI 更新")
        title.setObjectName("Title")
        head.addWidget(title)
        head.addStretch(1)
        self.status_badge = QLabel("SMAPI 状态：未检查")
        self.status_badge.setObjectName("Badge")
        head.addWidget(self.status_badge)
        root.addLayout(head)

        cards = QHBoxLayout()
        self.inst_lbl = self._card(cards, "已安装版本", "-")
        self.latest_lbl = self._card(cards, "最新版本", "-")
        self.integrity_lbl = self._card(cards, "完整性检查", "-")
        root.addLayout(cards)

        bar = QHBoxLayout()
        self.check_btn = QPushButton("检查更新")
        self.check_btn.setObjectName("Primary")
        self.check_btn.clicked.connect(self.check)
        self.install_btn = QPushButton("一键安装 / 修复 SMAPI")
        self.install_btn.setObjectName("Primary")
        self.install_btn.clicked.connect(lambda: self.download_and_install(auto=True, force=True))
        self.pkg_btn = QPushButton("下载安装包（不安装）")
        self.pkg_btn.clicked.connect(lambda: self.download_and_install(auto=False))
        self.official_btn = QPushButton("官方安装器（交互）")
        self.official_btn.setToolTip("在应用内控制台运行官方安装器，可用输入框回答它的提问")
        self.official_btn.clicked.connect(self.run_official_installer)
        self.page_btn = QPushButton("打开发布页")
        self.page_btn.clicked.connect(self._open_page)
        self.tr_btn = QPushButton("🤖 AI 翻译更新日志")
        self.tr_btn.setToolTip("把当前版本的更新日志翻译成中文（结果缓存，同一版本只翻一次）；按住 Ctrl 点击可强制重新翻译")
        self.tr_btn.setEnabled(False)
        self.tr_btn.clicked.connect(self._on_translate_clicked)
        self.orig_btn = QPushButton("看原文")
        self.orig_btn.setEnabled(False)
        self.orig_btn.clicked.connect(lambda: self._render(show_original=True))
        for b in (self.check_btn, self.install_btn, self.pkg_btn, self.official_btn,
                  self.page_btn, self.tr_btn, self.orig_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.prog = QProgressBar()
        self.prog.setMinimumWidth(160)
        self.prog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.prog.setVisible(False)
        pbar_row = QHBoxLayout()
        pbar_row.addWidget(self.prog, 1)
        root.addLayout(pbar_row)
        root.addLayout(bar)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        root.addWidget(self.body, 1)

        tip = QLabel(
            "「一键安装 / 修复」会下载官方安装包，把 SMAPI 本体和 .NET 宿主文件（hostpolicy.dll 等）"
            "复制进游戏目录，并自动生成 StardewModdingAPI.deps.json；原有文件会先备份到 %APPDATA%\\StardewModManager\\backup。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.ctx.smapiInfoChanged.connect(self.refresh_installed)
        self.refresh_installed()
        self._render()

    # ---------------- 小组件
    def _card(self, layout, title: str, value: str) -> QLabel:
        box = QWidget()
        box.setObjectName("Card")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 12)
        t = QLabel(title)
        t.setObjectName("Hint")
        v = QLabel(value)
        v.setStyleSheet("font-size:17px;font-weight:700;")
        v.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(v)
        layout.addWidget(box, 1)
        return v

    # ---------------- 主题
    def refresh_theme(self) -> None:
        """配色切换后重新渲染更新日志（HTML 里写的是当时的颜色）。"""
        try:
            self._render(show_original=bool(self.orig_btn.isEnabled() and "原文" in self.body.toPlainText()))
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 状态
    def refresh_installed(self) -> None:
        v = self.ctx.smapi_installed or self.ctx.config.get("last_smapi_version") or ""
        self.inst_lbl.setText(v or "未检测到")
        state = smapi.verify_smapi(self.ctx.game_dir) if self.ctx.game_dir else None
        if not self.ctx.game_dir:
            self.integrity_lbl.setText("未设置游戏目录")
        elif not state["installed"]:
            self.integrity_lbl.setText("未安装 SMAPI")
        elif state["ok"]:
            self.integrity_lbl.setText("正常")
        else:
            self.integrity_lbl.setText("缺少 " + "、".join(state["missing"][:3]))
        self._render()

    def _render(self, show_original: bool = False) -> None:
        latest = self.ctx.smapi_latest
        if not latest:
            self.latest_lbl.setText("-")
            self.tr_btn.setEnabled(False)
            self.orig_btn.setEnabled(False)
            self.body.setHtml(
                f'<div style="color:{C["muted"]};padding:8px;">点击「检查更新」从 GitHub 获取 SMAPI 最新版本。</div>'
            )
            return
        self.latest_lbl.setText(latest.get("version") or "-")
        inst = self.ctx.smapi_installed or ""
        if inst and _cmp_ge(inst, latest.get("version")):
            self.status_badge.setText("SMAPI 状态：已是最新")
            self.status_badge.setObjectName("OkBadge")
        else:
            self.status_badge.setText("SMAPI 状态：有新版本！" if inst else "SMAPI 状态：未安装")
            self.status_badge.setObjectName("WarnBadge")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        version = latest.get("version") or ""
        original = latest.get("body") or ""
        cached = self._notes_cache.get(version) or {}
        translated = "" if show_original else (cached.get("zh") or "")
        self.tr_btn.setEnabled(bool(original))
        if cached.get("zh"):
            self.tr_btn.setText("🔄 重新翻译（会消耗额度）")
        else:
            self.tr_btn.setText("🤖 AI 翻译更新日志")
        self.orig_btn.setEnabled(bool(translated))


        raw = translated or original
        body = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = re.sub(r"^###?\s*(.+)$", r"<b>\1</b>", body, flags=re.M)
        body = body.replace("\n", "<br>")
        note = ""
        if translated:
            note = (
                f'<div style="color:{C["accent"]};font-size:12px;margin-bottom:6px;">'
                f'以下是 AI 翻译（模型 {cached.get("model") or "-"}）</div>'
            )
        elif cached.get("zh") and show_original:
            note = f'<div style="color:{C["muted"]};font-size:12px;margin-bottom:6px;">原文</div>'
        self.body.setHtml(
            f'<div style="color:{C["accent"]};font-weight:700;font-size:15px;">'
            f'{latest.get("name") or version}</div>'
            f'<div style="color:{C["muted"]};">发布于 {latest.get("published") or "-"} · '
            f'<a style="color:{C["blue"]};" href="{latest.get("page")}">GitHub Release</a></div>'
            f'<hr style="border:none;border-top:1px solid {C["line"]};">{note}<div>{body}</div>'
        )

    # ---------------- AI 翻译更新日志
    def _load_notes_cache(self) -> None:
        try:
            if self._cache_path.exists():
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._notes_cache = data
        except Exception:  # noqa: BLE001
            self._notes_cache = {}

    def _save_notes_cache(self) -> None:
        try:
            self._cache_path.write_text(
                json.dumps(self._notes_cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_translate_clicked(self) -> None:
        """有缓存时按钮是「重新翻译」（会先确认）；没缓存时才真正翻译。"""
        from PySide6.QtWidgets import QApplication

        version = (self.ctx.smapi_latest or {}).get("version") or ""
        has_cache = bool((self._notes_cache.get(version) or {}).get("zh"))
        force = bool(QApplication.keyboardModifiers() & Qt.ControlModifier) or has_cache
        self.translate_notes(force=force)

    def translate_notes(self, force: bool = False) -> None:
        latest = self.ctx.smapi_latest
        if not latest or not (latest.get("body") or "").strip():
            QMessageBox.information(self, "没有更新日志", "先点「检查更新」拿到更新说明。")
            return
        version = latest.get("version") or ""
        cached = self._notes_cache.get(version) or {}
        # 已经翻过就直接显示缓存，绝不重复花 token（除非按住 Ctrl 点=重新翻译）
        if cached.get("zh") and not force:
            self._render()
            self.ctx.status.emit(f"已显示缓存的翻译（模型 {cached.get('model') or '-'}，未消耗额度）")
            return
        if cached.get("zh") and force:
            if QMessageBox.question(
                self, "重新翻译",
                f"SMAPI {version} 已经有缓存的译文了。\n\n重新翻译会再次消耗你的 token，确定吗？"
            ) != QMessageBox.Yes:
                return
        cfg = self.ctx.config
        if not cfg.get("ai_key"):
            QMessageBox.warning(self, "缺少 API Key", "请先到「设置 → AI 汉化」填好接口和 API Key。")
            return
        if self._tr_worker is not None and self._tr_worker.isRunning():
            QMessageBox.information(self, "正在翻译", "上一次翻译还没结束。")
            return
        self.tr_btn.setEnabled(False)
        self.tr_btn.setText("🤖 翻译中…")
        self.ctx.status.emit(f"正在翻译 SMAPI {latest.get('version')} 的更新日志…")
        worker = TranslateWorker(
            latest.get("body") or "",
            cfg.get("ai_base"),
            cfg.get("ai_key"),
            cfg.get("ai_model"),
            [m for m in (cfg.get("ai_models") or []) if m != cfg.get("ai_model")],
            self,
        )
        worker.done.connect(self._on_notes_translated)
        worker.finished.connect(worker.deleteLater)
        self._tr_worker = worker
        worker.start()

    def _on_notes_translated(self, text: str, model: str, err: str) -> None:
        self.tr_btn.setEnabled(True)
        if err:
            self.tr_btn.setText("🤖 AI 翻译更新日志")
            QMessageBox.critical(self, "翻译失败", err)
            return
        latest = self.ctx.smapi_latest or {}
        version = latest.get("version") or "unknown"
        self._notes_cache[version] = {"zh": text, "model": model, "time": time.strftime("%Y-%m-%d %H:%M")}
        self._save_notes_cache()
        if model and model != self.ctx.config.get("ai_model"):
            self.ctx.config.set("ai_model", model)
            self.ctx.config.save()
        self.ctx.status.emit(f"更新日志已翻译（模型 {model}，已缓存）")
        self._render()

    def _open_page(self) -> None:
        import webbrowser

        url = (self.ctx.smapi_latest or {}).get("page") or smapi.RELEASES_PAGE
        webbrowser.open(url)

    # ---------------- 检查
    def check(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.status_badge.setText("SMAPI 状态：检查中…")
        self.check_btn.setEnabled(False)
        self.ctx.update_smapi_installed()
        w = CheckWorker(self)
        w.done.connect(self._on_checked)
        w.finished.connect(w.deleteLater)
        self._worker = w
        w.start()

    def _on_checked(self, data, err: str) -> None:
        self.check_btn.setEnabled(True)
        if err or not data:
            self.status_badge.setText("SMAPI 状态：检查失败")
            self.status_badge.setObjectName("ErrBadge")
            self.status_badge.style().unpolish(self.status_badge)
            self.status_badge.style().polish(self.status_badge)
            self.body.setHtml(f'<div style="color:{C["red"]};">检查更新失败：{err}</div>')
            return
        self.ctx.smapi_latest = data
        self.ctx.config.update(last_smapi_check=data.get("published") or "")
        self.ctx.update_smapi_installed()
        self.ctx.status.emit(f"SMAPI 最新版本：{data.get('version')}")
        self._render()

    # ---------------- 下载 / 安装
    def download_and_install(self, auto: bool = True, force: bool = False) -> None:
        if self.ctx.runner.running:
            QMessageBox.information(self, "正在运行", "请先停止游戏进程，再进行安装。")
            return
        if not self.ctx.game_dir:
            QMessageBox.warning(self, "未设置游戏目录", "请先到「设置」页面选择游戏目录。")
            return
        latest = self.ctx.smapi_latest
        if not latest or not latest.get("installer_url"):
            if force:
                self.check()
                QMessageBox.information(self, "正在检查更新", "正在获取最新版本，请稍等一下再点一次。")
            else:
                QMessageBox.warning(self, "没有可用安装包", "请先检查更新。")
            return
        self.prog.setVisible(True)
        self.prog.setRange(0, 0)
        for b in (self.check_btn, self.install_btn, self.pkg_btn, self.official_btn):
            b.setEnabled(False)
        self.status_badge.setText("SMAPI 状态：安装中…")
        w = InstallWorker(latest["installer_url"], latest.get("version") or "latest", self.ctx.game_dir, auto, self)
        w.progress.connect(self._on_progress)
        w.message.connect(self.ctx.log)
        w.done.connect(lambda path, err: self._on_done(path, err, auto))
        w.finished.connect(w.deleteLater)
        self._dl = w
        w.start()

    def _on_progress(self, got: int, total: int) -> None:
        if total:
            self.prog.setRange(0, 100)
            self.prog.setValue(int(got * 100 / total))
        else:
            self.prog.setRange(0, 0)

    def _on_done(self, path: str, err: str, auto: bool) -> None:
        self.prog.setVisible(False)
        for b in (self.check_btn, self.install_btn, self.pkg_btn, self.official_btn):
            b.setEnabled(True)
        self.ctx.update_smapi_installed()
        self.refresh_installed()
        if err:
            QMessageBox.critical(self, "安装失败", err)
            return
        if auto:
            state = smapi.verify_smapi(self.ctx.game_dir)
            self.ctx.status.emit("SMAPI 安装完成" + (f"，版本 {state['version']}" if state["version"] else ""))
            QMessageBox.information(
                self,
                "完成",
                "SMAPI 已安装 / 修复完成。\n\n"
                f"版本：{state['version'] or '未知'}\n"
                f"游戏目录：{self.ctx.game_dir}\n\n"
                "现在可以到「运行控制台」点启动游戏了。",
            )
        else:
            QMessageBox.information(self, "下载完成", f"安装包已解压到：\n{path}")
            try:
                import os

                os.startfile(path)  # noqa: S606
            except Exception:  # noqa: BLE001
                pass

    def run_official_installer(self) -> None:
        base = config_dir() / "smapi_update"
        roots = [p for p in base.glob("SMAPI-*") if p.is_dir()] if base.exists() else []
        if not roots:
            QMessageBox.information(self, "还没有安装包", "请先点「下载安装包」或「一键安装 / 修复」。")
            return
        root = smapi.find_package_root(sorted(roots)[-1])
        try:
            program, args, cwd = smapi.build_install_command(root, self.ctx.game_dir)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "未找到安装器", str(exc))
            return
        if self.on_run:
            self.on_run(program, args, cwd, "SMAPI 官方安装器")
