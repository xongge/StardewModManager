"""Mod 配置编辑窗口：把 config.json 变成带中文说明的表单。

中文标签优先用 Mod 自带的 i18n/zh.json（键名写法做过归一化，
AutomationInterval ↔ config.automation-interval.name 也能对上），
剩下没有中文说明的项可以一键交给 AI 翻译并缓存。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import ai as ailab
from ... import modconfig as mc
from ..theme import C


class LabelWorker(QThread):
    """把缺失的配置项名称一次性发给 AI 翻译。"""

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


class ConfigEditor(QDialog):
    def __init__(self, mod, ctx=None, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.ctx = ctx
        self.setWindowTitle(f"配置 · {mod.name}")
        self.resize(800, 700)
        self._rows: list = []
        self._worker = None
        self._pending: list = []
        self._translated = 0

        config, i18n, path = mc.load_mod_config(Path(mod.folder))
        self.i18n = i18n
        self.path = path

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel(mod.name)
        title.setObjectName("Title")
        root.addWidget(title)
        self.sub = QLabel()
        self.sub.setObjectName("Hint")
        self.sub.setWordWrap(True)
        root.addWidget(self.sub)

        if config is None:
            self.sub.setText(
                f"没有找到 config.json：{path or Path(mod.folder) / 'config.json'}\n"
                "大多数 Mod 需要先进游戏一次才会生成配置文件；生成后回到这里就能图形化修改。"
            )
            row = QHBoxLayout()
            row.addStretch(1)
            close = QPushButton("关闭")
            close.clicked.connect(self.reject)
            row.addWidget(close)
            root.addLayout(row)
            return

        self.config = config
        zh_count = sum(1 for k in config if mc._lookup(i18n, k))
        self.sub.setText(
            f"{path}　·　{len(config)} 个顶层配置项，{zh_count} 项已用 Mod 自带的中文；"
            "没有中文的项可以点右下角「AI 汉化配置项」"
        )

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        form = QVBoxLayout(holder)
        form.setContentsMargins(2, 2, 8, 2)
        form.setSpacing(8)
        self.schema = mc.build_schema(config, i18n)
        self._apply_cached_labels(self.schema)
        for item in self.schema:
            self._add_item(form, item, ())
        form.addStretch(1)
        area.setWidget(holder)
        root.addWidget(area, 1)

        bottom = QHBoxLayout()
        self.tip = QLabel(self._source_hint())
        self.tip.setObjectName("Hint")
        bottom.addWidget(self.tip)
        self.ai_btn = QPushButton("🤖 AI 汉化配置项")
        self.ai_btn.setToolTip("把还没有中文说明的配置项一次性发给 AI 翻译（结果会缓存，不重复消耗 token）")
        self.ai_btn.clicked.connect(self.translate_labels)
        bottom.addWidget(self.ai_btn)
        bottom.addStretch(1)
        open_btn = QPushButton("打开所在文件夹")
        open_btn.clicked.connect(self._open_file)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        for b in (open_btn, cancel, save):
            bottom.addWidget(b)
        root.addLayout(bottom)

    # ---------------- 文案
    def _source_hint(self) -> str:
        total = len(self._rows)
        if not total:
            return ""
        return f"共 {total} 个配置项，其中 {self._translated} 个显示为中文"

    # ---------------- 中文标签缓存
    def _cache_key(self, path) -> str:
        return f"{self.mod.unique_id or self.mod.folder_name}::" + ".".join(path)

    def _apply_cached_labels(self, schema, parent_path=()) -> None:
        for item in schema:
            path = parent_path + (item["key"],)
            if item.get("type") == "group":
                self._apply_cached_labels(item.get("children") or [], path)
                continue
            if item.get("i18n"):
                self._translated += 1
                continue
            if self.ctx is not None:
                english = mc.humanize(item["key"])
                cached = self.ctx.labels.get(self._cache_key(path), english)
                if cached:
                    item["label"] = cached
                    self._translated += 1

    # ---------------- 构建界面
    def _add_item(self, layout, item: dict, parent_path: tuple) -> None:
        path = parent_path + (item["key"],)
        if item.get("type") == "group":
            box = QFrame()
            box.setObjectName("Card")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(12, 10, 12, 10)
            inner.setSpacing(6)
            head = QLabel(item["label"])
            head.setStyleSheet(f"font-weight:700;color:{C['accent']};")
            inner.addWidget(head)
            if item.get("help"):
                h = QLabel(item["help"])
                h.setObjectName("Hint")
                h.setWordWrap(True)
                inner.addWidget(h)
            for child in item.get("children") or []:
                self._add_item(inner, child, path)
            layout.addWidget(box)
            return

        row = QWidget()
        row.setObjectName("Card")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(12, 8, 12, 8)
        rl.setSpacing(4)

        label = QLabel(item["label"])
        label.setStyleSheet("font-weight:600;")
        rl.addWidget(label)
        keylbl = QLabel(f"config 键：{'.'.join(path)}" + ("" if item.get("i18n") else "（暂无中文，可用 AI 汉化）"))
        keylbl.setObjectName("Hint")
        rl.addWidget(keylbl)
        if item.get("help"):
            h = QLabel(item["help"])
            h.setObjectName("Hint")
            h.setWordWrap(True)
            rl.addWidget(h)

        widget = self._make_widget(item)
        if widget is not None:
            rl.addWidget(widget)
        layout.addWidget(row)
        self._rows.append(
            {
                "item": item,
                "path": path,
                "widget": widget,
                "kind": item["type"],
                "label_widget": label,
            }
        )

    def _make_widget(self, item: dict):
        kind, value = item["type"], item["value"]
        if kind == "bool":
            w = QCheckBox("开启（勾选）/ 关闭（不勾选）")
            w.setChecked(bool(value))
            return w
        if kind == "int":
            w = QSpinBox()
            w.setRange(-999999, 999999)
            w.setValue(int(value))
            w.setMaximumWidth(220)
            return w
        if kind == "float":
            w = QDoubleSpinBox()
            w.setRange(-999999.0, 999999.0)
            w.setDecimals(3)
            w.setValue(float(value))
            w.setMaximumWidth(220)
            return w
        if kind == "str":
            opts = item.get("options") or []
            if opts:
                w = QComboBox()
                for opt in opts:
                    text = mc.option_label(self.i18n, item["key"], opt) or opt
                    w.addItem(f"{text}  ({opt})", opt)
                idx = w.findData(str(value))
                if idx < 0:
                    w.addItem(str(value), str(value))
                    idx = w.count() - 1
                w.setCurrentIndex(idx)
            else:
                w = QLineEdit(str(value))
            w.setMaximumWidth(420)
            return w
        if kind == "list":
            w = QLineEdit(", ".join(str(v) for v in value))
            w.setToolTip("用英文逗号分隔")
            return w
        w = QLineEdit(json.dumps(value, ensure_ascii=False))
        return w

    # ---------------- 动作
    def _open_file(self) -> None:
        import os

        if self.path:
            os.startfile(str(Path(self.path).parent))  # noqa: S606

    def _set_value(self, data: dict, path: tuple, value) -> None:
        target = data
        for key in path[:-1]:
            nxt = target.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                target[key] = nxt
            target = nxt
        target[path[-1]] = value

    def _collect(self) -> dict:
        data = json.loads(json.dumps(self.config, ensure_ascii=False))
        for row in self._rows:
            path, widget, kind = row["path"], row["widget"], row["kind"]
            item = row["item"]
            if widget is None:
                continue
            old = item["value"]
            try:
                if kind == "bool":
                    value = bool(widget.isChecked())
                elif kind == "int":
                    value = int(widget.value())
                elif kind == "float":
                    value = float(widget.value())
                elif kind == "str":
                    value = widget.currentData() if isinstance(widget, QComboBox) else widget.text()
                elif kind == "list":
                    parts = [p.strip() for p in widget.text().split(",") if p.strip()]
                    sample = old[0] if isinstance(old, list) and old else ""
                    value = [coerce(p, sample) for p in parts]
                else:
                    value = json.loads(widget.text())
            except Exception:  # noqa: BLE001
                raise ValueError(f"配置项「{item['label']}」格式不对") from None
            self._set_value(data, path, value)
        return data

    def _save(self) -> None:
        try:
            data = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        try:
            mc.save_mod_config(Path(self.path), data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(self, "已保存", f"配置已写入\n{self.path}\n\n下次启动游戏生效。")
        self.accept()

    # ---------------- AI 汉化配置项
    def translate_labels(self) -> None:
        if self.ctx is None:
            return
        cfg = self.ctx.config
        if not cfg.get("ai_key"):
            QMessageBox.warning(self, "缺少 API Key", "请到「设置 → AI 汉化」填写 API Key。")
            return
        pending = []
        for idx, row in enumerate(self._rows):
            item = row["item"]
            if item.get("i18n"):
                continue
            english = mc.humanize(item["key"])
            key = ".".join(row["path"])
            if self.ctx.labels.get(self._cache_key(row["path"]), english):
                continue
            pending.append({"row": idx, "path": row["path"], "key": key, "english": english})
        if not pending:
            QMessageBox.information(self, "无需翻译", "所有配置项都已经有中文名了。")
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("🤖 翻译中…")
        entries = [{"id": str(p["row"]), "name": p["english"]} for p in pending]
        worker = LabelWorker(
            entries,
            cfg.get("ai_base"),
            cfg.get("ai_key"),
            cfg.get("ai_model"),
            [m for m in (cfg.get("ai_models") or []) if m != cfg.get("ai_model")],
            self,
        )
        worker.done.connect(self._on_labels, Qt.QueuedConnection)
        worker.done.connect(worker.deleteLater)
        self._worker = worker
        self._pending = pending
        worker.start()

    def _on_labels(self, pairs, used_model: str, err: str) -> None:
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("🤖 AI 汉化配置项")
        if err:
            QMessageBox.critical(self, "翻译失败", err)
            return
        if used_model and self.ctx and used_model != self.ctx.config.get("ai_model"):
            self.ctx.config.set("ai_model", used_model)
            self.ctx.config.save()
        by_row = {int(k): v for k, v in (pairs or {}).items() if str(k).isdigit()}
        count = 0
        for p in self._pending:
            zh = by_row.get(p["row"])
            if not zh:
                continue
            row = self._rows[p["row"]]
            row["item"]["label"] = zh
            widget = row.get("label_widget")
            if widget is not None:
                widget.setText(zh)
            self.ctx.labels.put(self._cache_key(p["path"]), p["english"], zh)
            count += 1
        self.ctx.labels.save()
        self._translated += count
        self.tip.setText(f"已汉化 {count} 个配置项（模型 {used_model}，已缓存）")


def coerce(text: str, sample):
    if isinstance(sample, bool):
        return text.strip().lower() in ("1", "true", "yes", "是", "on")
    if isinstance(sample, int):
        try:
            return int(text)
        except ValueError:
            return text
    if isinstance(sample, float):
        try:
            return float(text)
        except ValueError:
            return text
    return text
