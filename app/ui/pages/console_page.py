"""运行控制台页：应用内控制台（替代 CMD 窗口）。

- 一个按钮在「启动游戏 / 停止游戏」之间切换
- 输出按级别着色（错误红、警告黄）
- 右上角实时显示错误数 / 警告数
- 可选中复制、可一键复制全部
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import log_dir
from ...game import VANILLA_EXE
from .. import anim, decor
from ..theme import C

FILTERS = ["全部输出", "仅错误与警告", "仅错误"]


class ConsolePage(QWidget):
    repairRequested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._records: list = []
        self._max = int(ctx.config.get("max_console_lines") or 6000)
        self._running = False
        self._last_errors = 0
        self._last_warnings = 0
        self._pending: list = []
        self._flush_timer = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("运行控制台")
        title.setObjectName("Title")
        head.addWidget(title)
        self.dot = decor.PulseDot(self, decor.BLUE, 12, ctx.config)
        head.addWidget(self.dot)
        self.state_lbl = QLabel("未运行")
        self.state_lbl.setObjectName("Badge")
        head.addWidget(self.state_lbl)
        head.addStretch(1)
        self.err_badge = QLabel("✖ 错误 0")
        self.err_badge.setObjectName("ErrBadge")
        self.warn_badge = QLabel("⚠ 警告 0")
        self.warn_badge.setObjectName("WarnBadge")
        head.addWidget(self.warn_badge)
        head.addWidget(self.err_badge)
        root.addLayout(head)

        bar = QHBoxLayout()
        self.toggle = QPushButton("▶  启动游戏")
        self.toggle.setObjectName("Primary")
        self.toggle.setMinimumWidth(150)
        self.toggle.clicked.connect(self.toggle_game)
        bar.addWidget(self.toggle)

        self.vanilla = QPushButton("原版启动")
        self.vanilla.setToolTip("不加载 SMAPI / Mod，直接启动 Stardew Valley.exe")
        self.vanilla.clicked.connect(lambda: self.launch_game(vanilla=True))
        bar.addWidget(self.vanilla)

        self.filter_box = QComboBox()
        self.filter_box.addItems(FILTERS)
        self.filter_box.currentIndexChanged.connect(lambda _i: self._rerender())
        bar.addWidget(self.filter_box)

        self.autoscroll = QCheckBox("自动滚动")
        self.autoscroll.setChecked(True)
        bar.addWidget(self.autoscroll)

        self.copy_btn = QPushButton("复制选中")
        self.copy_btn.clicked.connect(self.copy_selection)
        self.copy_all = QPushButton("复制全部")
        self.copy_all.clicked.connect(self.copy_all_text)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.clear)
        self.log_btn = QPushButton("打开日志")
        self.log_btn.clicked.connect(self._open_logs)
        for b in (self.copy_btn, self.copy_all, self.clear_btn, self.log_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        # 诊断提示条
        self.banner = QFrame()
        self.banner.setObjectName("Card")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        self.banner_text.setStyleSheet(f"color:{C['yellow']};")
        bl.addWidget(self.banner_text, 1)
        fix = QPushButton("一键安装 / 修复 SMAPI")
        fix.setObjectName("Primary")
        fix.clicked.connect(self.repairRequested.emit)
        bl.addWidget(fix)
        hide = QPushButton("隐藏")
        hide.clicked.connect(lambda: self.banner.setVisible(False))
        bl.addWidget(hide)
        self.banner.setVisible(False)
        root.addWidget(self.banner)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(self._max + 200)
        font = QFont("Consolas", 10)
        font.setFamilies(["Consolas", "Cascadia Mono", "Microsoft YaHei UI", "Microsoft YaHei"])
        font.setStyleHint(QFont.Monospace)
        self.view.setFont(font)
        self.view.setStyleSheet(
            "background:%s; border:1px solid %s; border-radius:10px; color:%s;"
            " font-family: Consolas, 'Cascadia Mono', 'Microsoft YaHei UI', monospace; padding:10px;"
            % (C["bg2"], C["line"], C["text"])
        )
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        root.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("向进程输入文字后回车（官方 SMAPI 安装器需要选择时用）")
        self.input.returnPressed.connect(self._send_input)
        self.input.setEnabled(False)
        bottom.addWidget(self.input, 1)
        self.hint = QLabel("日志同时保存到 " + str(log_dir()))
        self.hint.setObjectName("Hint")
        bottom.addWidget(self.hint)
        root.addLayout(bottom)

        r = ctx.runner
        r.line.connect(self._append)
        r.stats.connect(self._on_stats)
        r.state.connect(self._on_state)
        r.smapiVersion.connect(self._on_smapi_version)
        r.hint.connect(self._on_hint)
        ctx.smapiInfoChanged.connect(self._check_integrity)

        self._info("控制台就绪。SMAPI 的输出会显示在这里，不会再弹出 CMD 黑窗。")

    # ------------------------------------------------------------ 主题
    def refresh_theme(self) -> None:
        """配色变化后刷新内联样式（提示条 + 已输出的内容）。"""
        try:
            self.banner_text.setStyleSheet(f"color:{C['yellow']};")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._rerender()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.view.setStyleSheet(
                "background:%s; border:1px solid %s; border-radius:10px; color:%s;"
                " font-family: Consolas, 'Cascadia Mono', 'Microsoft YaHei UI', monospace; padding:10px;"
                % (C["bg2"], C["line"], C["text"])
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 启动 / 停止
    def toggle_game(self) -> None:
        if self.ctx.runner.running:
            self.stop_game()
        else:
            self.launch_game()

    def launch_game(self, vanilla: bool = False) -> None:
        gd = self.ctx.game_dir
        if not gd:
            QMessageBox.warning(self, "未设置游戏目录", "请先到「设置」页面选择星露谷物语游戏目录。")
            return
        if self.ctx.runner.running:
            return
        from ...game import detect_game_dir, validate_game_dir

        info = validate_game_dir(gd)
        if not info["has_game"]:
            better = detect_game_dir()
            tip = (
                f"当前游戏目录：\n{gd}\n\n这里没有游戏本体 Stardew Valley.exe，"
                "只有 SMAPI 的残留文件，所以启动会报 hostpolicy.dll 之类的错误。"
            )
            if better:
                tip += f"\n\n检测到真正的游戏目录：\n{better}\n\n是否自动切换过去？"
                if QMessageBox.question(self, "游戏目录不对", tip) == QMessageBox.Yes:
                    self.ctx.config.set("game_dir", better)
                    self.ctx.config.set("mods_dir", str(Path(better) / "Mods"))
                    self.ctx.config.save()
                    self.ctx.update_smapi_installed()
                    self.ctx.status.emit(f"游戏目录已切换到 {better}")
                    gd = better
                else:
                    return
            else:
                QMessageBox.warning(self, "游戏目录不对", tip)
                return
        if vanilla:
            from ...game import find_vanilla_exe

            exe, note = find_vanilla_exe(gd)
            label = "星露谷物语（原版）"
            if note:
                self._info(f"[管理器] {note}")
        else:
            exe = self.ctx.smapi_exe
            label = "SMAPI"
        if not Path(exe).exists():
            QMessageBox.warning(
                self,
                "找不到可执行文件",
                f"{exe}\n\n请到「SMAPI 更新」页面点「一键安装 / 修复 SMAPI」。",
            )
            return
        if not vanilla:
            from ...smapi import verify_smapi

            state = verify_smapi(gd)
            if state["missing"]:
                self._show_banner(
                    "检测到 SMAPI 组件不完整，缺少："
                    + "、".join(state["missing"])
                    + "。直接启动会报 hostpolicy.dll 之类的错误，请先点右侧按钮修复。"
                )
        args = []
        extra = str(self.ctx.config.get("extra_args") or "").strip()
        if extra:
            args = extra.split()
        self.ctx.runner.start(exe, args, cwd=gd, label=label)

    def start_process(self, program: str, args=None, cwd: str = "", label: str = "") -> bool:
        if self.ctx.runner.running:
            QMessageBox.information(self, "正在运行", "已有进程在运行，请先停止。")
            return False
        return self.ctx.runner.start(program, args, cwd=cwd, label=label)

    def stop_game(self) -> None:
        if not self.ctx.runner.stop():
            self._info("当前没有正在运行的进程。")

    def _send_input(self) -> None:
        text = self.input.text()
        if not text:
            return
        if self.ctx.runner.write_input(text):
            self._append(f"> {text}", "sys", f'<span style="color:{C["muted"]};">&gt; {text}</span>')
        self.input.clear()

    # ------------------------------------------------------------ 输出
    def _pass(self, level: str) -> bool:
        mode = self.filter_box.currentIndex()
        if mode == 1:
            return level in ("error", "warn", "sys")
        if mode == 2:
            return level in ("error", "sys")
        return True

    def _append(self, raw: str, level: str, html: str) -> None:
        self._records.append((level, html, raw))
        if len(self._records) > self._max:
            del self._records[: len(self._records) - self._max]
        if not self._pass(level):
            return
        # 攒一批再刷新，SMAPI 刷屏时不会卡界面
        self._pending.append(html)
        if len(self._pending) >= 40:
            self._flush()
        elif self._flush_timer is None:
            self._flush_timer = QTimer(self)
            self._flush_timer.setSingleShot(True)
            self._flush_timer.timeout.connect(self._flush)
            self._flush_timer.start(60)

    def _flush(self) -> None:
        if self._flush_timer is not None and self._flush_timer.isActive():
            self._flush_timer.stop()
        if not self._pending:
            return
        for html in self._pending:
            self.view.appendHtml(html)
        self._pending.clear()
        self._scroll()

    def _info(self, text: str) -> None:
        color = C["sys"]
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append(text, "sys", f'<span style="color:{color};">{esc}</span>')

    def _rerender(self) -> None:
        self.view.clear()
        for level, html, _raw in self._records:
            if self._pass(level):
                self.view.appendHtml(html)
        self._scroll()

    def _scroll(self) -> None:
        if self.autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def copy_selection(self) -> None:
        cursor = self.view.textCursor()
        text = cursor.selectedText().replace("\u2029", "\n")
        if not text:
            self._info("没有选中文字，可先用「复制全部」。")
            return
        QApplication.clipboard().setText(text)
        self._info(f"已复制 {len(text)} 个字符到剪贴板。")

    def copy_all_text(self) -> None:
        text = "\n".join(raw for _lvl, _html, raw in self._records)
        QApplication.clipboard().setText(text)
        self._info(f"已复制全部 {len(text)} 个字符到剪贴板。")

    def clear(self) -> None:
        self._records.clear()
        self.view.clear()

    def _open_logs(self) -> None:
        try:
            os.startfile(str(log_dir()))  # noqa: S606
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 状态
    def _on_stats(self, errors: int, warnings: int) -> None:
        self.err_badge.setText(f"✖ 错误 {errors}")
        self.warn_badge.setText(f"⚠ 警告 {warnings}")
        self.err_badge.setObjectName("ErrBadge" if errors else "OkBadge")
        self.warn_badge.setObjectName("WarnBadge" if warnings else "OkBadge")
        for b in (self.err_badge, self.warn_badge):
            b.style().unpolish(b)
            b.style().polish(b)
        if errors > self._last_errors:
            anim.pulse(self.err_badge)
        if warnings > self._last_warnings:
            anim.pulse(self.warn_badge)
        self._last_errors, self._last_warnings = errors, warnings

    def _on_state(self, state: str) -> None:
        self._running = state in ("running", "starting")
        if self._running:
            self.toggle.setText("■  停止游戏")
            self.toggle.setObjectName("Danger")
            self.state_lbl.setText("运行中" if state == "running" else "启动中…")
        else:
            self.toggle.setText("▶  启动游戏")
            self.toggle.setObjectName("Primary")
            self.state_lbl.setText("未运行")
        self.dot.set_running(self._running)
        self.dot.set_color(decor.GREEN if self._running else decor.BLUE)
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)
        self.input.setEnabled(state == "running")
        self.vanilla.setEnabled(not self._running)

    def _on_smapi_version(self, version: str) -> None:
        self.ctx.smapi_installed = version
        self.ctx.smapiInfoChanged.emit()

    def _on_hint(self, kind: str) -> None:
        if kind == "smapi-host":
            self._show_banner(
                "SMAPI 启动失败：游戏目录里缺少 .NET 宿主文件（hostpolicy.dll / coreclr.dll 等），"
                "或环境变量 DOTNET_ROOT 指向了错误位置。点右侧按钮可以自动重装/修复 SMAPI。"
            )

    def _show_banner(self, text: str) -> None:
        self.banner_text.setText(text)
        self.banner.setVisible(True)

    def show_warning(self, text: str) -> None:
        self._show_banner(text)

    def _check_integrity(self) -> None:
        if not self.ctx.game_dir or self._running:
            return
        from ...smapi import verify_smapi

        state = verify_smapi(self.ctx.game_dir)
        if state["missing"] and state["installed"]:
            self._show_banner(
                "SMAPI 组件不完整，缺少：" + "、".join(state["missing"]) + "，请点右侧按钮修复。"
            )
