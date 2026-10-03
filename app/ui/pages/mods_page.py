"""Mod 管理页：左侧分类，中间列表（勾选启用/停用），右侧详情 + 配置编辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import ai as ailab
from ... import mods as modlib
from ... import updates as updatelib
from ...config import cache_path
from .. import anim
from ..theme import C
from .config_editor import ConfigEditor
from .settings_page import open_path

CAT_ALL = "全部 Mod"
CAT_ON = "已启用"
CAT_OFF = "已停用"
CAT_ISSUE = "有问题的"
CAT_UPDATE = "可更新的"
CATS_FIXED = [CAT_ALL, CAT_ON, CAT_OFF, CAT_ISSUE, CAT_UPDATE]


class UpdateWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object, str)

    def __init__(self, mods, nexus_key, nexus_cookie="", cache=None, parent=None):
        super().__init__(parent)
        self.mods = mods
        self.nexus_key = nexus_key
        self.nexus_cookie = nexus_cookie
        self.cache = cache
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102
        try:
            result = updatelib.check_all(
                self.mods,
                self.nexus_key,
                self.nexus_cookie,
                workers=6,
                progress=lambda d, t, name: self.progress.emit(d, t, name),
                should_stop=lambda: self._stop,
                cache=self.cache,
            )
            self.done.emit(result, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit({}, str(exc))


class TranslateWorker(QThread):
    done = Signal(object, str, str)

    def __init__(self, entries, base, key, model, fallbacks=None, parent=None):
        super().__init__(parent)
        self.entries = entries
        self.base = base
        self.key = key
        self.model = model
        self.fallbacks = fallbacks or []

    def run(self) -> None:  # noqa: D102
        try:
            pairs, used = ailab.translate_names_ex(
                self.entries, self.base, self.key, self.model, fallbacks=self.fallbacks
            )
            self.done.emit(pairs, used, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit({}, "", str(exc))


class ModRow(QTreeWidgetItem):
    def __init__(self, mod, label: str, original: str = "", update: dict | None = None):
        super().__init__([""])
        self.mod = mod
        self.label = label
        self.original = original
        self.update = update or {}
        self.setCheckState(0, Qt.Checked if mod.enabled else Qt.Unchecked)
        tip = f"文件夹：{mod.folder_name}\nUniqueID：{mod.unique_id or '-'}"
        if original:
            tip += f"\n原名：{original}"
        if getattr(mod, "zh_name", ""):
            tip += "\n中文名来自该 Mod 自带的 i18n/zh.json"
        info = self.update
        if info.get("status") == "new":
            tip += f"\n可更新：{mod.display_version} → {info.get('latest')}（{info.get('source')}）\n{info.get('url') or ''}"
        elif info.get("status") in ("ok", "error", "skip") and info.get("note"):
            tip += f"\n更新检查：{info.get('note')}"
        self.setToolTip(1, tip)
        self.refresh_style(label, original)

    def refresh_style(self, label: str, original: str = "") -> None:
        self.setText(2, self.mod.author or "-")
        info = self.update
        if info.get("status") == "new" and info.get("latest"):
            self.setText(3, f"{self.mod.display_version} → {info['latest']}")
            self.setForeground(3, QColor(C["accent"]))
        else:
            self.setText(3, self.mod.display_version)
        self.setText(4, self.mod.kind)
        marks = []
        if self.mod.has_error:
            marks.append("✖")
        if self.mod.has_warn:
            marks.append("⚠")
        if info.get("status") == "new":
            marks.append("⬆")
        text = label if (not original or original == label) else f"{label}  ·  {original}"
        self.setText(1, f"{' '.join(marks)} {text}".strip())
        if self.mod.has_error:
            for col in range(5):
                self.setForeground(col, QColor(C["red"]))
        elif self.mod.has_warn:
            for col in range(5):
                self.setForeground(col, QColor(C["yellow"]))
        elif not self.mod.enabled:
            for col in range(5):
                self.setForeground(col, QColor(C["muted"]))
        else:
            for col in range(5):
                self.setForeground(col, QColor(C["text"]))


class ModsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._loading = False
        self._current_cat = CAT_ALL
        self._keyword = ""
        self._tr_worker = None
        self._upd_worker = None
        self.updates: dict = {}
        try:
            self._cache = updatelib.UpdateCache(cache_path("updates_cache.json"))
            self.updates = {
                k: v for k, v in self._cache.data.items() if isinstance(v, dict) and v.get("status")
            }
        except Exception:  # noqa: BLE001
            self._cache = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Mod 管理")
        title.setObjectName("Title")
        head.addWidget(title)
        head.addStretch(1)
        self.badge_total = QLabel("共 0")
        self.badge_total.setObjectName("Badge")
        self.badge_err = QLabel("错误 0")
        self.badge_err.setObjectName("ErrBadge")
        self.badge_warn = QLabel("警告 0")
        self.badge_warn.setObjectName("WarnBadge")
        for b in (self.badge_total, self.badge_warn, self.badge_err):
            head.addWidget(b)
        root.addLayout(head)

        # 工具栏分两行，窄窗口也不会挤在一起
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索 Mod 名称 / 中文名 / 作者 / UniqueID…")
        self.search.setMinimumWidth(220)
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search, 1)
        self.ai_btn = QPushButton("🤖 AI 汉化名称")
        self.ai_btn.setToolTip("把还没有中文名的 Mod 一次性发给 AI 翻译（结果会缓存，不重复消耗 token）")
        self.ai_btn.clicked.connect(self.translate_names)
        self.update_btn = QPushButton("🔄 检查更新")
        self.update_btn.setToolTip("按 manifest 里的 UpdateKeys 查询 Nexus / GitHub 最新版本")
        self.update_btn.clicked.connect(self.check_updates)
        self.refresh = QPushButton("重新扫描")
        self.refresh.clicked.connect(self.ctx.refresh_mods)
        self.folder_btn = QPushButton("打开 Mod 目录")
        self.folder_btn.clicked.connect(lambda: open_path(self.ctx.mods_dir))
        for b in (self.ai_btn, self.update_btn, self.refresh, self.folder_btn):
            bar.addWidget(b)
        root.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(8)
        self.write_btn = QPushButton("写入 manifest")
        self.write_btn.setToolTip("把汉化后的中文名写进各 Mod 的 manifest.json，游戏里（GMCM 菜单/模组列表）也显示中文；会先备份原名")
        self.write_btn.clicked.connect(self.write_names_to_manifest)
        self.restore_btn = QPushButton("恢复原名")
        self.restore_btn.setToolTip("从 manifest.json.original 备份恢复被改过的 Name")
        self.restore_btn.clicked.connect(self.restore_names)
        self.enable_all = QPushButton("全部启用")
        self.disable_all = QPushButton("全部停用")
        self.enable_all.clicked.connect(lambda: self._bulk(True))
        self.disable_all.clicked.connect(lambda: self._bulk(False))
        self.show_orig = QCheckBox("显示原名")
        self.show_orig.setChecked(bool(self.ctx.config.get("show_original_name")))
        self.show_orig.stateChanged.connect(self._toggle_original)
        for b in (self.write_btn, self.restore_btn, self.enable_all, self.disable_all, self.show_orig):
            bar2.addWidget(b)
        bar2.addStretch(1)
        root.addLayout(bar2)

        split = QSplitter(Qt.Horizontal)
        self.cats = QListWidget()
        self.cats.setFixedWidth(190)
        self.cats.currentItemChanged.connect(self._on_cat)
        split.addWidget(self.cats)

        right = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["启用", "模组", "作者", "版本", "类型"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.tree.setColumnWidth(0, 56)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, w in ((2, 150), (3, 90), (4, 100)):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, w)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_config())
        right.addWidget(self.tree)

        detail_box = QWidget()
        dl = QVBoxLayout(detail_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setMinimumHeight(140)
        dl.addWidget(self.detail, 1)
        actions = QHBoxLayout()
        self.cfg_btn = QPushButton("编辑配置")
        self.cfg_btn.setObjectName("Primary")
        self.cfg_btn.setToolTip("读取该 Mod 的 config.json，配合它的中文 i18n 生成图形化设置窗口")
        self.cfg_btn.clicked.connect(self.edit_config)
        self.open_btn = QPushButton("打开文件夹")
        self.open_btn.clicked.connect(self._open_folder)
        self.cn_btn = QPushButton("手动改名（中文）")
        self.cn_btn.setToolTip("不调用 AI，直接给这个 Mod 起一个中文名")
        self.cn_btn.clicked.connect(self.edit_name)
        self.cfg_hint = QLabel("双击列表中的 Mod 也可以打开配置")
        self.cfg_hint.setObjectName("Hint")
        for b in (self.cfg_btn, self.open_btn, self.cn_btn, self.cfg_hint):
            actions.addWidget(b)
        actions.addStretch(1)
        dl.addLayout(actions)
        right.addWidget(detail_box)
        right.setSizes([480, 260])
        split.addWidget(right)
        split.setSizes([190, 900])
        root.addWidget(split, 1)

        self.ctx.modsChanged.connect(self.reload)
        self.status = QLabel("准备就绪")
        self.status.setObjectName("Hint")
        root.addWidget(self.status)
        self.reload()

    # ---------------- 分类
    def _rebuild_cats(self) -> None:
        counts = {
            CAT_ALL: len(self.ctx.mods),
            CAT_ON: sum(1 for m in self.ctx.mods if m.enabled),
            CAT_OFF: sum(1 for m in self.ctx.mods if not m.enabled),
            CAT_ISSUE: sum(1 for m in self.ctx.mods if m.problems),
            CAT_UPDATE: sum(1 for m in self.ctx.mods if self._update_of(m).get("status") == "new"),
        }
        kinds = {}
        for m in self.ctx.mods:
            kinds[m.kind] = kinds.get(m.kind, 0) + 1
        self.cats.blockSignals(True)
        self.cats.clear()
        matched = False
        for name in CATS_FIXED:
            it = QListWidgetItem(f"{name}   ({counts.get(name, 0)})")
            it.setData(Qt.UserRole, name)
            self.cats.addItem(it)
            if name == self._current_cat:
                self.cats.setCurrentItem(it)
                matched = True
        sep = QListWidgetItem("— 按类型 —")
        sep.setFlags(Qt.NoItemFlags)
        sep.setForeground(QColor(C["muted"]))
        self.cats.addItem(sep)
        for kind in modlib.KINDS:
            if not kinds.get(kind):
                continue
            it = QListWidgetItem(f"{kind}   ({kinds[kind]})")
            it.setData(Qt.UserRole, kind)
            self.cats.addItem(it)
            if kind == self._current_cat:
                self.cats.setCurrentItem(it)
                matched = True
        if not matched:
            self._current_cat = CAT_ALL
            self.cats.setCurrentRow(0)
        self.cats.blockSignals(False)

    def _on_cat(self, cur, _prev) -> None:
        if cur is None:
            return
        data = cur.data(Qt.UserRole)
        if data:
            self._current_cat = data
            self._fill_tree()

    def _update_of(self, mod) -> dict:
        if not getattr(mod, "unique_id", ""):
            return {}
        return self.updates.get(mod.unique_id) or {}

    # ---------------- 过滤
    def _match(self, mod) -> bool:
        cat = self._current_cat
        if cat == CAT_ON and not mod.enabled:
            return False
        if cat == CAT_OFF and mod.enabled:
            return False
        if cat == CAT_ISSUE and not mod.problems:
            return False
        if cat == CAT_UPDATE and self._update_of(mod).get("status") != "new":
            return False
        if cat in modlib.KINDS and mod.kind != cat:
            return False
        kw = self._keyword
        if kw:
            zh = self.ctx.translated_name(mod)
            hay = (
                f"{mod.name} {zh} {getattr(mod, 'zh_name', '')} {mod.author} "
                f"{mod.unique_id} {mod.folder_name} {mod.description}"
            ).lower()
            if kw not in hay:
                return False
        return True

    def _on_search(self, text: str) -> None:
        self._keyword = (text or "").strip().lower()
        self._fill_tree()

    def _toggle_original(self, _state) -> None:
        self.ctx.config.set("show_original_name", self.show_orig.isChecked())
        self.ctx.config.save()
        self._fill_tree()

    # ---------------- 填充
    def reload(self) -> None:
        self._rebuild_cats()
        self._fill_tree()
        s = self.ctx.stats()
        self.badge_total.setText(f"共 {s['total']} 个")
        self.badge_err.setText(f"错误 {s['errors']}")
        self.badge_warn.setText(f"警告 {s['warnings']}")
        self.badge_err.setObjectName("ErrBadge" if s["errors"] else "OkBadge")
        self.badge_warn.setObjectName("WarnBadge" if s["warnings"] else "OkBadge")
        for b in (self.badge_err, self.badge_warn):
            b.style().unpolish(b)
            b.style().polish(b)
        prev = getattr(self, "_prev_counts", (0, 0))
        if s["errors"] > prev[0]:
            anim.pulse(self.badge_err)
        if s["warnings"] > prev[1]:
            anim.pulse(self.badge_warn)
        self._prev_counts = (s["errors"], s["warnings"])
        if not self.ctx.mods_dir:
            self.status.setText("尚未设置 Mod 文件夹，请到「设置」页面选择。")
        elif not self.ctx.mods_dir.exists():
            self.status.setText(f"Mod 文件夹不存在：{self.ctx.mods_dir}")
        else:
            self.status.setText(
                f"{self.ctx.mods_dir}　·　启用 {s['enabled']} / 停用 {s['disabled']}"
            )

    def _fill_tree(self) -> None:
        self._loading = True
        self.tree.clear()
        show_orig = self.show_orig.isChecked()
        for mod in self.ctx.mods:
            if not self._match(mod):
                continue
            zh = "" if show_orig else self.ctx.translated_name(mod)
            label = zh or mod.name
            original = mod.name if (zh and zh != mod.name) else ""
            self.tree.addTopLevelItem(ModRow(mod, label, original, self._update_of(mod)))
        self._loading = False
        anim.fade_in(self.tree, 180)
        if self.tree.topLevelItemCount() == 0:
            self.detail.setHtml(
                f'<div style="color:{C["muted"]};padding:12px;">没有符合条件的 Mod。</div>'
            )

    # ---------------- 交互
    def _on_item_changed(self, item, col) -> None:
        if self._loading or col != 0 or not isinstance(item, ModRow):
            return
        want_enabled = item.checkState(0) == Qt.Checked
        mod = item.mod
        if want_enabled == mod.enabled:
            return
        self._apply_toggle(mod, want_enabled)

    def _apply_toggle(self, mod, want_enabled: bool) -> bool:
        md = self.ctx.mods_dir
        if md is None:
            QMessageBox.warning(self, "未设置目录", "请先在设置里指定 Mod 文件夹。")
            self.reload()
            return False
        ok, msg = modlib.toggle_mod(mod, self.ctx.disabled_dir_name, md, want_enabled)
        if not ok:
            QMessageBox.critical(self, "操作失败", f"{mod.folder_name}\n{msg}")
            self.ctx.status.emit(f"操作失败：{msg}")
            self.reload()
            return False
        self.ctx.status.emit(f"{'已启用' if want_enabled else '已停用'}：{mod.name}")
        self.ctx.refresh_mods()
        return True

    def _selected_mods(self):
        return [it.mod for it in self.tree.selectedItems() if isinstance(it, ModRow)]

    def _current_mod(self):
        mods = self._selected_mods()
        return mods[0] if mods else None

    def _bulk(self, enable: bool) -> None:
        if self.ctx.mods_dir is None:
            QMessageBox.warning(self, "未设置目录", "请先在设置里指定 Mod 文件夹。")
            return
        mods = [m for m in self._selected_mods() if m.enabled != enable] or [
            m for m in self.ctx.mods if m.enabled != enable and self._match(m)
        ]
        if not mods:
            QMessageBox.information(self, "无需操作", "没有需要变更的 Mod。")
            return
        tip = "启用" if enable else "停用"
        if len(mods) > 3 and QMessageBox.question(
            self, f"批量{tip}", f"确定要{tip} {len(mods)} 个 Mod 吗？"
        ) != QMessageBox.Yes:
            return
        failed = 0
        for mod in mods:
            ok, _ = modlib.toggle_mod(mod, self.ctx.disabled_dir_name, self.ctx.mods_dir, enable)
            failed += 0 if ok else 1
        self.ctx.status.emit(f"批量{tip}完成，失败 {failed} 个")
        self.ctx.refresh_mods()

    def _open_folder(self) -> None:
        mod = self._current_mod()
        if mod:
            open_path(mod.folder)

    def _on_select(self, cur, _prev) -> None:
        if not isinstance(cur, ModRow):
            return
        self._last_mod = cur.mod
        self.detail.setHtml(self._mod_html(cur.mod))

    # ---------------- 配置编辑
    def edit_config(self) -> None:
        mod = self._current_mod()
        if mod is None:
            QMessageBox.information(self, "请先选择 Mod", "在上面的列表里点一个 Mod，再点「编辑配置」。")
            return
        dlg = ConfigEditor(mod, self.ctx, self)
        dlg.exec()

    def edit_name(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        mod = self._current_mod()
        if mod is None:
            return
        current = self.ctx.names.get(mod.unique_id, mod.name) if mod.unique_id else ""
        current = current or self.ctx.translated_name(mod)
        text, ok = QInputDialog.getText(self, "中文名", f"{mod.name} 的中文名：", text=current or "")
        if ok:
            if not mod.unique_id:
                QMessageBox.warning(self, "无法保存", "这个 Mod 没有 UniqueID，不能单独命名。")
                return
            self.ctx.names.put(mod.unique_id, mod.name, text.strip())
            self.ctx.names.save()
            self.status.setText(f"已设置中文名：{text.strip() or '(空)'}")
            self.ctx.status.emit(f"{mod.name} → {text.strip()}")
            self.ctx.modsChanged.emit()

    # ---------------- AI 汉化
    def translate_names(self) -> None:
        cfg = self.ctx.config
        if not cfg.get("ai_key"):
            QMessageBox.warning(self, "缺少 API Key", "请到「设置 → AI 汉化」填写 API Key。")
            return
        pending = self.ctx.names.pending(self.ctx.mods)
        if not pending:
            QMessageBox.information(self, "无需翻译", "所有 Mod 都已经有中文名了。\n（可在「设置」里关闭汉化，或手动改名）")
            return
        if self._tr_worker is not None and self._tr_worker.isRunning():
            QMessageBox.information(self, "正在翻译", "上一次翻译还没结束，请稍等。")
            return
        if QMessageBox.question(
            self,
            "AI 汉化名称",
            f"将把 {len(pending)} 个 Mod 名称一次性发给 AI 翻译。\n"
            "已经翻译过的不会重复发送。是否继续？",
        ) != QMessageBox.Yes:
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("🤖 翻译中…")
        self.ctx.status.emit(f"正在翻译 {len(pending)} 个 Mod 名称…")
        w = TranslateWorker(
            pending,
            cfg.get("ai_base"),
            cfg.get("ai_key"),
            cfg.get("ai_model"),
            [m for m in (cfg.get("ai_models") or []) if m != cfg.get("ai_model")],
            self,
        )
        w.done.connect(self._on_translated)
        w.finished.connect(w.deleteLater)
        self._tr_worker = w
        w.start()

    def _on_translated(self, pairs, used_model: str, err: str) -> None:
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("🤖 AI 汉化名称")
        if err:
            QMessageBox.critical(self, "翻译失败", err)
            self.ctx.status.emit("翻译失败：" + err.splitlines()[0])
            return
        if used_model and used_model != self.ctx.config.get("ai_model"):
            self.ctx.config.set("ai_model", used_model)
            self.ctx.config.save()
            self.ctx.status.emit(f"原模型不可用，已自动改用 {used_model}")
        by_id = {m.unique_id: m for m in self.ctx.mods if m.unique_id}
        count = 0
        for uid, zh in (pairs or {}).items():
            mod = by_id.get(uid)
            if mod is None:
                continue
            self.ctx.names.put(uid, mod.name, zh)
            count += 1
        self.ctx.names.save()
        self.ctx.status.emit(f"翻译完成：{count} 个 Mod 名称已汉化（模型 {used_model}，已缓存）")
        self.ctx.modsChanged.emit()
        if self.ctx.config.get("write_name_to_manifest") and count:
            self.write_names_to_manifest()

    # ---------------- 主题
    def refresh_theme(self) -> None:
        """配色切换后重刷列表文字与详情面板。

        列表项的文字颜色是建行时写进 QTreeWidgetItem 的，不重刷的话从明亮切回
        深色会保留深色文字，在深色背景上就看不清了。
        """
        for i in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(i)
            if isinstance(row, ModRow):
                row.refresh_style(row.label, row.original)
        cur = self.tree.currentItem()
        mod = cur.mod if isinstance(cur, ModRow) else getattr(self, "_last_mod", None)
        if mod is not None:
            try:
                self.detail.setHtml(self._mod_html(mod))
            except Exception:  # noqa: BLE001
                pass
        self._rebuild_cats()

    # ---------------- 检测模组更新
    def check_updates(self, force: bool = True) -> None:
        if self._upd_worker is not None and self._upd_worker.isRunning():
            QMessageBox.information(self, "正在检查", "上一次检查还没结束。")
            return
        mods = list(self.ctx.mods)
        if not mods:
            QMessageBox.information(self, "没有 Mod", "先扫描出 Mod 再检查更新。")
            return
        nexus_mods = sum(1 for m in mods if any(k.lower().startswith("nexus:") for k in (m.update_keys or [])))
        key = str(self.ctx.config.get("nexus_key") or "").strip()
        cookie = str(self.ctx.config.get("nexus_cookie") or "").strip()
        if nexus_mods and not key and not cookie and not self.ctx.config.get("_nexus_warned"):
            self.ctx.config.set("_nexus_warned", True)
            QMessageBox.information(
                self,
                "Nexus 还需要配置一下",
                f"有 {nexus_mods} 个 Mod 来自 Nexus，需要先给它一个凭据才能查更新：\n\n"
                "① Cookie（推荐，免申请）：浏览器登录 nexusmods.com → 按 F12 → "
                "「网络 / Network」→ 刷新页面 → 点任意请求 → "
                "「请求标头」里的 Cookie 整行复制，粘贴到「设置 → 模组更新检测」里的 Nexus Cookie 框。\n\n"
                "② API Key：点设置里的「打开 API Key 页面」，生成一个复制过来。\n\n"
                "（GitHub 来源的 Mod 不需要这些，会照常检查）",
            )
        self.update_btn.setEnabled(False)
        self.update_btn.setText("🔄 检查中…")
        self.status.setText("正在检查模组更新…")
        worker = UpdateWorker(mods, key, cookie, self._cache, self)
        worker.progress.connect(self._on_update_progress)
        worker.done.connect(self._on_updates_done)
        worker.finished.connect(worker.deleteLater)
        self._upd_worker = worker
        worker.start()

    def _on_update_progress(self, done: int, total: int, name: str) -> None:
        self.status.setText(f"检查更新 {done}/{total}：{name}")
        self.ctx.status.emit(f"检查模组更新 {done}/{total}")

    def _on_updates_done(self, result, err: str) -> None:
        self.update_btn.setEnabled(True)
        self.update_btn.setText("🔄 检查更新")
        if err:
            QMessageBox.critical(self, "检查失败", err)
            return
        self.updates = result or {}
        if self._cache is not None:
            for uid, info in self.updates.items():
                self._cache.put(uid, info)
            self._cache.save()
        new = [u for u in self.updates.values() if u.get("status") == "new"]
        errs = [u for u in self.updates.values() if u.get("status") == "error"]
        skipped = [u for u in self.updates.values() if u.get("status") == "skip"]
        self.reload()
        if new:
            self._current_cat = CAT_UPDATE
            self._rebuild_cats()
            self._fill_tree()
        self.status.setText(
            f"检查完成：{len(new)} 个可更新 · {len(errs)} 个查询失败 · {len(skipped)} 个需要 Key 或不支持"
        )
        self.ctx.status.emit(self.status.text())
        if new:
            lines = "\n".join(
                f"• {u.get('name')}：{u.get('current')} → {u.get('latest')}" for u in new[:12]
            )
            more = f"\n… 共 {len(new)} 个" if len(new) > 12 else ""
            QMessageBox.information(self, "发现新版本", f"以下 Mod 可以更新：\n\n{lines}{more}")
        else:
            QMessageBox.information(self, "检查完成", "没有发现可更新的 Mod。")

    # ---------------- 把中文名写进 manifest
    def _name_pairs(self):
        pairs = []
        for mod in self.ctx.mods:
            zh = self.ctx.translated_name(mod)
            if zh and zh != mod.name:
                pairs.append((mod, zh))
        return pairs

    def write_names_to_manifest(self) -> None:
        pairs = self._name_pairs()
        if not pairs:
            QMessageBox.information(
                self, "没有可写入的名称", "先点「🤖 AI 汉化名称」，或手动给 Mod 起中文名。"
            )
            return
        if QMessageBox.question(
            self,
            "写入 manifest.json",
            f"将把 {len(pairs)} 个 Mod 的中文名写进各自的 manifest.json，"
            "游戏内的模组列表 / GMCM 菜单就会显示中文。\n\n"
            "修改前会自动备份成 manifest.json.original，随时可以点「恢复原名」。是否继续？",
        ) != QMessageBox.Yes:
            return
        ok = fail = 0
        errors = []
        for mod, zh in pairs:
            good, msg = modlib.write_manifest_name(Path(mod.folder), zh)
            if good:
                ok += 1
            else:
                fail += 1
                errors.append(f"{mod.folder_name}: {msg}")
        self.status.setText(f"已写入 {ok} 个，失败 {fail} 个")
        self.ctx.status.emit(self.status.text())
        if errors:
            QMessageBox.warning(self, "部分失败", "\n".join(errors[:8]))
        self.ctx.refresh_mods()

    def restore_names(self) -> None:
        targets = [m for m in self.ctx.mods if modlib.has_manifest_backup(Path(m.folder))]
        if not targets:
            QMessageBox.information(self, "没有备份", "没有找到 manifest.json.original 备份。")
            return
        if QMessageBox.question(
            self, "恢复原名", f"将恢复 {len(targets)} 个 Mod 的 manifest 原名，确定吗？"
        ) != QMessageBox.Yes:
            return
        ok = fail = 0
        for mod in targets:
            good, _msg = modlib.restore_manifest_name(Path(mod.folder))
            ok += 1 if good else 0
            fail += 0 if good else 1
        self.status.setText(f"已恢复 {ok} 个，失败 {fail} 个")
        self.ctx.status.emit(self.status.text())
        self.ctx.refresh_mods()

    # ---------------- 详情
    def _mod_html(self, mod) -> str:
        def esc(t):
            return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        sev = {"error": C["red"], "warn": C["yellow"], "info": C["muted"]}
        probs = "".join(
            f'<div style="color:{sev[p.severity]};">● {esc(p.text)}</div>' for p in mod.problems
        ) or f'<div style="color:{C["accent"]};">● 未发现问题</div>'
        state = (
            f'<span style="color:{C["accent"]};">已启用</span>'
            if mod.enabled
            else f'<span style="color:{C["muted"]};">已停用</span>'
        )
        links = ""
        for k in mod.update_keys:
            if k.lower().startswith("nexus:"):
                links += f'<a style="color:{C["blue"]};" href="https://www.nexusmods.com/stardewvalley/mods/{esc(k.split(":", 1)[1])}">Nexus</a> '
        cp_line = ""
        if mod.content_pack_for:
            cp_line = f'<div style="color:{C["muted"]};">内容包框架：{esc(mod.content_pack_for)}</div>'
        zh = self.ctx.translated_name(mod)
        src = self.ctx.name_source(mod)
        zh_line = (
            f'<div style="color:{C["accent"]};font-weight:700;">{esc(zh)}'
            f'<span style="color:{C["muted"]};font-weight:400;font-size:12px;">　（{esc(src)}）</span></div>'
            if zh and zh != mod.name
            else ""
        )
        cfg_path = Path(mod.folder) / "config.json"
        cfg_line = (
            f'<div style="color:{C["accent"]};">● 已有配置文件 config.json，可以点下面「编辑配置」图形化修改</div>'
            if cfg_path.exists()
            else f'<div style="color:{C["muted"]};">● 还没有 config.json（进一次游戏后一般会生成）</div>'
        )
        info = self._update_of(mod)
        up_line = ""
        if info.get("status") == "new":
            up_line = (
                f'<div style="color:{C["accent"]};font-weight:700;">⬆ 有新版本：'
                f'{esc(mod.display_version)} → {esc(info.get("latest"))}'
                f'　<a style="color:{C["blue"]};" href="{esc(info.get("url") or "#")}">前往下载</a></div>'
            )
        elif info:
            note = info.get("note") or {"ok": "已是最新版本", "skip": "无法自动检查", "error": "查询失败"}.get(
                info.get("status"), ""
            )
            up_line = f'<div style="color:{C["muted"]};">● 更新检查：{esc(note)}</div>'
        return f"""
        {zh_line}
        <div style="font-size:15px;font-weight:700;">{esc(mod.name)}</div>
        <div style="color:{C['muted']};">{esc(mod.author or '未知作者')} · v{esc(mod.display_version)} · {esc(mod.kind)} · {state}</div>
        <hr style="border:none;border-top:1px solid {C['line']};">
        <div style="color:{C['muted']};">UniqueID：{esc(mod.unique_id or '-')}　最低 SMAPI：{esc(mod.min_api or '-')}</div>
        <div style="color:{C['muted']};">文件夹：{esc(mod.folder_name)}</div>
        <div style="color:{C['muted']};">路径：{esc(mod.folder)}</div>
        {cp_line}
        <div style="margin:6px 0;">{esc(mod.description)}</div>
        <div style="margin-top:8px;">{probs}</div>
        <div style="margin-top:6px;">{cfg_line}</div>
        <div style="margin-top:6px;">{up_line}</div>
        <div style="margin-top:6px;">{links}</div>
        """
