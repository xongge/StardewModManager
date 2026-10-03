"""设置页：Mod 文件夹、游戏目录、停用目录名、启动参数。"""
from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import ai as ailab
from ... import updates as updatelib
from ...config import config_dir, log_dir
from .. import theme as themelib
from ..theme import C

CREATE_NO_WINDOW = 0x08000000
NEXUS_API_PAGE = "https://www.nexusmods.com/users/myaccount?tab=api"


class NexusTestWorker(QThread):
    done = Signal(object)

    def __init__(self, nexus_key: str, nexus_cookie: str, parent=None):
        super().__init__(parent)
        self.nexus_key = nexus_key
        self.nexus_cookie = nexus_cookie

    def run(self) -> None:  # noqa: D102
        client = updatelib.NexusClient(self.nexus_key, self.nexus_cookie)
        try:
            self.done.emit(updatelib.nexus_self_test(client))
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc), "method": client.how(), "html": ""})


def _qcolor(hexcolor: str):
    from PySide6.QtGui import QColor

    color = QColor(hexcolor)
    return color if color.isValid() else QColor("#4cc38a")


class TestApiWorker(QThread):
    """列出模型并逐个探测哪些当前真正可用。"""

    done = Signal(object, object, str)

    def __init__(self, base: str, key: str, current: str, parent=None):
        super().__init__(parent)
        self.base = base
        self.key = key
        self.current = current

    def run(self) -> None:  # noqa: D102
        try:
            listed = ailab.list_models(self.base, self.key)
        except Exception as exc:  # noqa: BLE001
            self.done.emit([], {}, str(exc))
            return
        candidates = []
        for m in [self.current, *listed, *ailab.KNOWN_MODELS]:
            if m and m not in candidates:
                candidates.append(m)
        ok, bad = ailab.probe_models(self.base, self.key, candidates, limit=12)
        self.done.emit(ok, bad, "")


def open_path(path) -> None:
    p = Path(str(path or ""))
    if not p.exists():
        QMessageBox.warning(None, "路径不存在", f"找不到：{p}")
        return
    try:
        os.startfile(str(p))  # noqa: S606
    except Exception:  # noqa: BLE001
        subprocess.Popen(["explorer", str(p)], creationflags=CREATE_NO_WINDOW)


class PathRow(QWidget):
    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.btn = QPushButton("浏览…")
        self.btn.setFixedWidth(84)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value or "")


class SettingsPage(QWidget):
    def __init__(self, ctx, on_saved=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_saved = on_saved
        cfg = ctx.config

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        holder = QWidget()
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(22, 18, 22, 18)
        inner.setSpacing(14)
        area.setWidget(holder)
        root.addWidget(area)
        root = inner  # 之后所有内容都加到可滚动区域里

        title = QLabel("设置")
        title.setObjectName("Title")
        root.addWidget(title)
        sub = QLabel("配置游戏与 Mod 目录，管理器会读取目录下所有 Mod 的 manifest.json 与配置文件")
        sub.setObjectName("Sub")
        root.addWidget(sub)

        box = QGroupBox("目录")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setSpacing(10)

        self.game = PathRow(r"例如 C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley")
        self.game.setText(cfg.get("game_dir"))
        self.game.btn.clicked.connect(lambda: self._pick_dir(self.game))

        self.mods = PathRow(r"例如 C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley\Mods")
        self.mods.setText(cfg.get("mods_dir"))
        self.mods.btn.clicked.connect(lambda: self._pick_dir(self.mods))

        det = QPushButton("自动检测")
        det.clicked.connect(self._auto_detect)
        det.setFixedWidth(84)
        gwrap = QWidget()
        gl = QHBoxLayout(gwrap)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)
        gl.addWidget(self.game, 1)
        gl.addWidget(det)

        form.addRow("游戏目录", gwrap)
        form.addRow("Mod 文件夹", self.mods)

        self.disabled_name = QLineEdit(cfg.get("disabled_dir_name"))
        self.disabled_name.setToolTip("被停用的 Mod 会被移动到 Mod 文件夹同级的这个目录里")
        form.addRow("停用目录名", self.disabled_name)

        self.args = QLineEdit(cfg.get("extra_args"))
        self.args.setPlaceholderText("传给 SMAPI 的额外启动参数（一般留空）")
        form.addRow("启动参数", self.args)
        root.addWidget(box)

        box2 = QGroupBox("行为")
        v2 = QVBoxLayout(box2)
        self.auto = QCheckBox("启动时自动检测游戏目录")
        self.auto.setChecked(bool(cfg.get("auto_detect")))
        self.chk_smapi = QCheckBox("启动时自动检查 SMAPI 更新")
        self.chk_smapi.setChecked(bool(cfg.get("auto_check_smapi")))
        self.translate_enabled = QCheckBox("在列表里显示 AI 汉化名称")
        self.translate_enabled.setChecked(bool(cfg.get("translate_enabled", True)))
        self.animations = QCheckBox("界面过渡动效（页面淡入、导航高亮滑动）")
        self.animations.setChecked(bool(cfg.get("animations", True)))
        self.confirm_exit = QCheckBox("退出时如果游戏仍在运行，先询问是否停止")
        self.confirm_exit.setChecked(True)
        for w in (self.auto, self.chk_smapi, self.translate_enabled, self.animations, self.confirm_exit):
            v2.addWidget(w)
        root.addWidget(box2)

        # ---------------- AI 汉化
        box3 = QGroupBox("AI 汉化（任意 OpenAI 兼容接口）")
        form3 = QFormLayout(box3)
        form3.setSpacing(10)
        form3.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form3.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.ai_base = QLineEdit(cfg.get("ai_base"))
        self.ai_base.setPlaceholderText("https://你的服务地址/v1")
        form3.addRow("接口地址", self.ai_base)
        self.ai_key = QLineEdit(cfg.get("ai_key"))
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText("sk-...")
        self.show_key = QCheckBox("显示")
        self.show_key.stateChanged.connect(
            lambda s: self.ai_key.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password)
        )
        keyrow = QWidget()
        kl = QHBoxLayout(keyrow)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(self.ai_key, 1)
        kl.addWidget(self.show_key)
        form3.addRow("API Key", keyrow)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        self.ai_model.setToolTip("留空表示自动挑一个当前可用的模型；点下面按钮可自动探测")
        self.ai_model.addItem("")
        self.ai_model.addItems(ailab.KNOWN_MODELS)
        self.ai_model.setCurrentText(cfg.get("ai_model") or "")
        form3.addRow("模型", self.ai_model)
        self.test_btn = QPushButton("测试连接并自动选择模型")
        self.test_btn.clicked.connect(self.test_api)
        form3.addRow("", self.test_btn)
        self.ai_state = QLabel("")
        self.ai_state.setObjectName("Hint")
        self.ai_state.setWordWrap(True)
        form3.addRow("", self.ai_state)

        cache_row = QWidget()
        cl = QHBoxLayout(cache_row)
        cl.setContentsMargins(0, 0, 0, 0)
        self.cache_info = QLabel("")
        self.cache_info.setObjectName("Hint")
        cl.addWidget(self.cache_info, 1)
        clear_btn = QPushButton("清空翻译缓存")
        clear_btn.setToolTip("缓存保存在磁盘上，清空后下次会重新消耗 token 翻译")
        clear_btn.clicked.connect(self.clear_cache)
        cl.addWidget(clear_btn)
        form3.addRow("翻译缓存", cache_row)
        root.addWidget(box3)

        # ---------------- 文件位置
        box4 = QGroupBox("文件位置")
        v4 = QVBoxLayout(box4)
        self.paths_info = QLabel("")
        self.paths_info.setObjectName("Hint")
        self.paths_info.setWordWrap(True)
        self.paths_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v4.addWidget(self.paths_info)
        prow = QHBoxLayout()
        open_cfg_file = QPushButton("直接打开配置文件")
        open_cfg_file.setObjectName("Primary")
        open_cfg_file.clicked.connect(self.open_config_file)
        open_dir = QPushButton("打开所在文件夹")
        open_dir.clicked.connect(lambda: open_path(config_dir()))
        open_logs = QPushButton("打开日志目录")
        open_logs.clicked.connect(lambda: open_path(log_dir()))
        for b in (open_cfg_file, open_dir, open_logs):
            prow.addWidget(b)
        prow.addStretch(1)
        v4.addLayout(prow)
        root.addWidget(box4)

        # ---------------- 模组更新
        box5 = QGroupBox("模组更新检测（Nexus / GitHub）")
        v5 = QVBoxLayout(box5)
        v5.setSpacing(10)

        hint5 = QLabel(
            "GitHub 来源的 Mod 不需要任何配置。Nexus 来源的两种方式选一个即可：\n"
            "① Cookie（推荐，免申请）：浏览器登录 nexusmods.com → 按 F12 → 「网络 / Network」→ "
            "刷新任意一个 nexusmods.com 页面 → 点第一个请求 → 「请求标头 / Request Headers」里"
            "找到 Cookie 那一行，把整行的值复制过来（要包含 cf_clearance 和 nexusmods_session）。\n"
            "② API Key（更稳）：点下面按钮打开 N 网 API 页面，点 Generate 生成一个 Personal API Key 复制过来。"
        )
        hint5.setObjectName("Hint")
        hint5.setWordWrap(True)
        v5.addWidget(hint5)

        self.nexus_cookie = QLineEdit(cfg.get("nexus_cookie"))
        self.nexus_cookie.setEchoMode(QLineEdit.Password)
        self.nexus_cookie.setPlaceholderText("在这里粘贴浏览器里的整行 Cookie")
        self.show_cookie = QCheckBox("显示")
        self.show_cookie.stateChanged.connect(
            lambda s: self.nexus_cookie.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password)
        )
        crow_w = QWidget()
        cl2 = QHBoxLayout(crow_w)
        cl2.setContentsMargins(0, 0, 0, 0)
        cl2.addWidget(self.nexus_cookie, 1)
        cl2.addWidget(self.show_cookie)
        v5.addWidget(QLabel("① Nexus Cookie"))
        v5.addWidget(crow_w)

        self.nexus_key = QLineEdit(cfg.get("nexus_key"))
        self.nexus_key.setEchoMode(QLineEdit.Password)
        self.nexus_key.setPlaceholderText("（可选）粘贴 Personal API Key")
        self.show_nexus = QCheckBox("显示")
        self.show_nexus.stateChanged.connect(
            lambda s: self.nexus_key.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password)
        )
        nrow = QWidget()
        nl = QHBoxLayout(nrow)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(self.nexus_key, 1)
        nl.addWidget(self.show_nexus)
        v5.addWidget(QLabel("② Nexus API Key"))
        v5.addWidget(nrow)

        trow = QHBoxLayout()
        self.nexus_test_btn = QPushButton("测试 Nexus 连接（用 Content Patcher 试）")
        self.nexus_test_btn.clicked.connect(self.test_nexus)
        open_api = QPushButton("打开 API Key 页面")
        open_api.clicked.connect(lambda: webbrowser.open(NEXUS_API_PAGE))
        open_site = QPushButton("打开 N 网首页登录")
        open_site.clicked.connect(lambda: webbrowser.open("https://www.nexusmods.com/"))
        for b in (self.nexus_test_btn, open_api, open_site):
            trow.addWidget(b)
        trow.addStretch(1)
        v5.addLayout(trow)
        self.nexus_state = QLabel("")
        self.nexus_state.setObjectName("Hint")
        self.nexus_state.setWordWrap(True)
        v5.addWidget(self.nexus_state)

        self.write_manifest = QCheckBox("AI 汉化后，把中文名同时写进 manifest.json（游戏内也显示中文）")
        self.write_manifest.setChecked(bool(cfg.get("write_name_to_manifest", False)))
        v5.addWidget(self.write_manifest)
        root.addWidget(box5)

        # ---------------- 颜色自定义（放最下面）
        box6 = QGroupBox("颜色自定义")
        v6 = QVBoxLayout(box6)
        v6.setSpacing(10)
        mode_hint = QLabel("深色 / 明亮切换在左侧导航栏底部的按钮上；下面只细调具体颜色。")
        mode_hint.setObjectName("Hint")
        mode_hint.setWordWrap(True)
        v6.addWidget(mode_hint)
        hint6 = QLabel(
            "点色块选颜色，立即生效并保存到 config.json；「恢复默认配色」可一键还原。"
            "切换深色 / 明亮会同时调整标题栏与所有面板底色。"
        )
        hint6.setObjectName("Hint")
        hint6.setWordWrap(True)
        v6.addWidget(hint6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self._swatches: dict = {}
        for row, (key, label, _target) in enumerate(themelib.CUSTOMIZABLE):
            name = QLabel(label)
            name.setMinimumWidth(130)
            swatch = QPushButton()
            swatch.setFixedSize(46, 24)
            swatch.setCursor(Qt.PointingHandCursor)
            value_label = QLabel("")
            value_label.setObjectName("Hint")
            value_label.setMinimumWidth(80)
            clear_btn = QPushButton("默认")
            clear_btn.setFixedWidth(60)
            clear_btn.clicked.connect(lambda _=False, k=key: self.reset_color(k))
            swatch.clicked.connect(lambda _=False, k=key: self.pick_color(k))
            grid.addWidget(name, row, 0)
            grid.addWidget(swatch, row, 1)
            grid.addWidget(value_label, row, 2)
            grid.addWidget(clear_btn, row, 3)
            grid.setColumnStretch(2, 1)
            self._swatches[key] = (swatch, value_label)
        v6.addLayout(grid)
        self.preview = QFrame()
        self.preview.setObjectName("Card")
        pv = QVBoxLayout(self.preview)
        pv.setContentsMargins(14, 12, 14, 12)
        self.preview_title = QLabel("预览：这段文字用的是「正文文字」颜色")
        pv.addWidget(self.preview_title)
        self.preview_hint = QLabel("这一行用的是「次要文字」颜色 · 背景是「卡片 / 面板」")
        pv.addWidget(self.preview_hint)
        pvbtn_row = QHBoxLayout()
        pvbtn_row.addWidget(QPushButton("普通按钮"))
        b = QPushButton("主按钮")
        b.setObjectName("Primary")
        pvbtn_row.addWidget(b)
        pvbtn_row.addStretch(1)
        pv.addLayout(pvbtn_row)
        v6.addWidget(self.preview)

        crow = QHBoxLayout()
        reset_all = QPushButton("恢复默认配色")
        reset_all.clicked.connect(self.reset_all_colors)
        crow.addWidget(reset_all)
        crow.addStretch(1)
        v6.addLayout(crow)
        root.addWidget(box6)

        row = QHBoxLayout()
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        rescan = QPushButton("保存并重新扫描")
        rescan.clicked.connect(lambda: (self.save(), self._rescan()))
        for b in (save, rescan):
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

        root.addStretch(1)
        self.reload()

    # ---------------- 页面显示时刷新
    def on_shown(self) -> None:
        self.reload()
        self.refresh_cache_info()
        self.refresh_colors()

    def refresh_cache_info(self) -> None:
        names = len(getattr(self.ctx, "names", None).data) if getattr(self.ctx, "names", None) else 0
        labels = len(getattr(self.ctx, "labels", None).data) if getattr(self.ctx, "labels", None) else 0
        self.cache_info.setText(
            f"已缓存 {names} 个 Mod 名称、{labels} 个配置项名称（保存在磁盘，重启/换会话都不会重翻）"
        )
        self.paths_info.setText(
            f"配置文件：{config_dir() / 'config.json'}\n"
            f"翻译缓存：name_map.json / label_map.json（同上目录）\n"
            f"图标：由配置文件里的 \"icon\" 字段决定，当前 = "
            f"{self.ctx.config.get('icon') or '（未设置，用程序目录的 icon.ico）'}"
        )

    def open_config_file(self) -> None:
        path = self.ctx.config.ensure_file()
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:  # noqa: BLE001
            open_path(path.parent)

    def clear_cache(self) -> None:
        if QMessageBox.question(
            self, "清空缓存", "清空后下次汉化会重新消耗 token，确定吗？"
        ) != QMessageBox.Yes:
            return
        for cache in (self.ctx.names, self.ctx.labels):
            cache.data = {}
            cache.save()
        self.refresh_cache_info()
        self.ctx.status.emit("翻译缓存已清空")

    # ---------------- 主题
    def refresh_theme(self) -> None:
        """配色切换后刷新色块、预览卡与状态文字。"""
        try:
            self.refresh_colors()
            self.nexus_state.setStyleSheet(f"color:{C['muted']};" if not self.nexus_state.text() else self.nexus_state.styleSheet())
            self.ai_state.setStyleSheet(self.ai_state.styleSheet())
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 颜色
    def refresh_colors(self) -> None:
        palette = themelib.build_palette(self.ctx.config)
        for key, _label, target in themelib.CUSTOMIZABLE:
            swatch, value_label = self._swatches[key]
            color = palette.get(target, themelib.DEFAULT_COLORS[target])
            swatch.setStyleSheet(
                f"background:{color}; border:1px solid {themelib.shade(color, 0.6)}; border-radius:6px;"
            )
            custom = themelib.is_hex(self.ctx.config.get(key))
            value_label.setText(color + ("（自定义）" if custom else "（默认）"))
        try:
            self.preview.setStyleSheet(
                f"#Card {{ background: {palette['panel']}; border:1px solid {palette['line']};"
                f" border-radius:10px; }}"
            )
            self.preview_title.setStyleSheet(f"color:{palette['text']};font-weight:600;")
            self.preview_hint.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        except Exception:  # noqa: BLE001
            pass

    def pick_color(self, key: str) -> None:
        target = dict((k, t) for k, _l, t in themelib.CUSTOMIZABLE)[key]
        current = themelib.build_palette(self.ctx.config).get(target, "#000000")
        color = QColorDialog.getColor(
            _qcolor(current), self, "选择颜色", QColorDialog.DontUseNativeDialog
        )
        if not color.isValid():
            return
        self.ctx.config.set(key, color.name())
        self.ctx.config.save()
        self.refresh_colors()
        self._live_apply()
        self.ctx.status.emit(f"已应用颜色：{key} = {color.name()}")

    def reset_color(self, key: str) -> None:
        self.ctx.config.set(key, "")
        self.ctx.config.save()
        self.refresh_colors()
        self._live_apply()

    def reset_all_colors(self) -> None:
        for key, _label, _target in themelib.CUSTOMIZABLE:
            self.ctx.config.set(key, "")
        self.ctx.config.save()
        self.refresh_colors()
        self._live_apply()

    def _live_apply(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication

            themelib.apply_theme(QApplication.instance(), self.ctx.config)
            if self.on_saved:
                self.on_saved()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 行为
    def _pick_dir(self, row: PathRow) -> None:
        start = row.text() or self.ctx.game_dir or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if d:
            row.setText(d)
            if row is self.game and not self.mods.text():
                self.mods.setText(str(Path(d) / "Mods"))

    def _auto_detect(self) -> None:
        from ...game import default_mods_dir, detect_game_dir

        gd = detect_game_dir()
        if gd:
            self.game.setText(gd)
            if not self.mods.text():
                self.mods.setText(default_mods_dir(gd))
            QMessageBox.information(self, "检测成功", f"已找到游戏目录：\n{gd}")
        else:
            QMessageBox.warning(self, "未找到", "没能自动检测到游戏目录，请手动选择。")

    def test_nexus(self) -> None:
        key = self.nexus_key.text().strip()
        cookie = self.nexus_cookie.text().strip()
        if not key and not cookie:
            QMessageBox.warning(
                self, "还没配置",
                "请先填 Nexus Cookie（或者 API Key）。\n\n"
                "Cookie 获取：浏览器登录 nexusmods.com → F12 → Network → 刷新页面 → "
                "点任意请求 → Request Headers 里的 Cookie 整行复制过来。",
            )
            return
        self.nexus_test_btn.setEnabled(False)
        self.nexus_state.setStyleSheet(f"color:{C['muted']};")
        self.nexus_state.setText("正在测试（用 Content Patcher 试一次）…")
        worker = NexusTestWorker(key, cookie, self)
        worker.done.connect(self._on_nexus_test)
        worker.finished.connect(worker.deleteLater)
        self._nexus_tester = worker
        worker.start()

    def _on_nexus_test(self, info) -> None:
        self.nexus_test_btn.setEnabled(True)
        method = info.get("method") or "?"
        if info.get("ok"):
            self.nexus_state.setStyleSheet(f"color:{C['accent']};")
            self.nexus_state.setText(
                f"连接成功（方式：{method}）· Content Patcher 最新版本：{info.get('version')}"
                f"{('　' + info.get('title')) if info.get('title') else ''}\n"
                "现在回「模组管理」点「🔄 检查更新」就会用这个凭据查询。"
            )
            return
        self.nexus_state.setStyleSheet(f"color:{C['red']};")
        msg = f"失败（方式：{method}）：{info.get('error')}"
        if info.get("html"):
            dump = config_dir() / "nexus_debug.html"
            try:
                dump.write_text(info["html"], encoding="utf-8")
                msg += f"\n页面已保存到 {dump}（解析不出来时把这个文件发我）"
            except Exception:  # noqa: BLE001
                pass
        self.nexus_state.setText(msg)

    def save(self) -> None:
        cfg = self.ctx.config
        cfg.set("game_dir", self.game.text())
        cfg.set("mods_dir", self.mods.text())
        cfg.set("disabled_dir_name", self.disabled_name.text().strip() or "Mods.disabled")
        cfg.set("extra_args", self.args.text().strip())
        cfg.set("auto_detect", self.auto.isChecked())
        cfg.set("auto_check_smapi", self.chk_smapi.isChecked())
        cfg.set("translate_enabled", self.translate_enabled.isChecked())
        cfg.set("animations", self.animations.isChecked())
        cfg.set("ai_base", self.ai_base.text().strip() or ailab.DEFAULT_BASE)
        cfg.set("ai_key", self.ai_key.text().strip())
        cfg.set("ai_model", self.ai_model.currentText().strip())
        cfg.set("nexus_key", self.nexus_key.text().strip())
        cfg.set("nexus_cookie", self.nexus_cookie.text().strip())
        cfg.set("write_name_to_manifest", self.write_manifest.isChecked())
        cfg.save()
        self.ctx.status.emit("设置已保存")
        if self.on_saved:
            self.on_saved()

    def test_api(self) -> None:
        key = self.ai_key.text().strip()
        if not key:
            QMessageBox.warning(self, "缺少 Key", "请先填写 API Key。")
            return
        self.test_btn.setEnabled(False)
        self.ai_state.setStyleSheet(f"color:{C['muted']};")
        self.ai_state.setText("正在连接并逐个测试模型（约几秒）…")
        worker = TestApiWorker(
            self.ai_base.text().strip(), key, self.ai_model.currentText().strip(), self
        )
        worker.done.connect(self._on_test_done)
        worker.finished.connect(worker.deleteLater)
        self._tester = worker
        worker.start()

    def _on_test_done(self, models, bad, err: str) -> None:
        self.test_btn.setEnabled(True)
        if err:
            self.ai_state.setStyleSheet(f"color:{C['red']};")
            self.ai_state.setText("连接失败：" + err)
            return
        current = self.ai_model.currentText().strip()
        if not models:
            self.ai_state.setStyleSheet(f"color:{C['red']};")
            detail = "；".join(f"{k}: {v[:60]}" for k, v in list((bad or {}).items())[:2])
            self.ai_state.setText("没有可用模型。" + detail)
            return
        # 只把真正可用的模型放进下拉框，避免选中一个 404 的模型
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        self.ai_model.addItems(models)
        keep = current if current in models else models[0]
        self.ai_model.setCurrentText(keep)
        self.ai_model.blockSignals(False)
        if keep != current:
            self.ai_state.setStyleSheet(f"color:{C['yellow']};")
            self.ai_state.setText(
                f"原模型 {current or '(空)'} 当前不可用，已自动改用 {keep}。可用："
                + "、".join(models[:8])
            )
        else:
            self.ai_state.setStyleSheet(f"color:{C['accent']};")
            self.ai_state.setText(f"连接成功，可用模型：{'、'.join(models[:8])}")
        # 记住可用模型，翻译时按顺序回退
        self.ctx.config.set("ai_models", models)
        self.ctx.config.set("ai_model", keep)
        self.ctx.config.set("ai_base", self.ai_base.text().strip() or ailab.DEFAULT_BASE)
        self.ctx.config.set("ai_key", self.ai_key.text().strip())
        self.ctx.config.save()
        if bad:
            broken = "、".join(list(bad)[:5])
            self.ai_state.setToolTip(f"当前不可用的模型：{broken}")

    def _rescan(self) -> None:
        self.ctx.update_smapi_installed()
        self.ctx.refresh_mods()

    def reload(self) -> None:
        cfg = self.ctx.config
        self.game.setText(cfg.get("game_dir"))
        self.mods.setText(cfg.get("mods_dir"))
        self.disabled_name.setText(cfg.get("disabled_dir_name"))
        self.args.setText(cfg.get("extra_args"))
        self.ai_base.setText(cfg.get("ai_base"))
        self.ai_key.setText(cfg.get("ai_key"))
        self.ai_model.setCurrentText(cfg.get("ai_model") or "")
        self.translate_enabled.setChecked(bool(cfg.get("translate_enabled", True)))
        self.animations.setChecked(bool(cfg.get("animations", True)))
        self.nexus_key.setText(cfg.get("nexus_key") or "")
        self.nexus_cookie.setText(cfg.get("nexus_cookie") or "")
        self.write_manifest.setChecked(bool(cfg.get("write_name_to_manifest", False)))
        self.refresh_cache_info()
        self.refresh_colors()
