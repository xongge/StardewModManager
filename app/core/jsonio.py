"""JSON 读写：容忍 BOM / 注释 / 尾随逗号的解析 + 原子写入。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def tolerant_json(text: str):
    """解析游戏 Mod 那种"不太标准"的 JSON。

    容忍：UTF-8 BOM、// 行注释、/* */ 块注释、对象/数组的尾随逗号。
    """
    text = str(text).lstrip("\ufeff")
    out: list[str] = []
    i, n, in_str, esc = 0, len(text), False, False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = _strip_trailing_commas(cleaned)
    return json.loads(cleaned)


def _strip_trailing_commas(text: str) -> str:
    """去掉 } / ] 前面多余的逗号（字符串内部的逗号不动）。"""
    out: list[str] = []
    in_str = esc = False
    pending = -1          # 待定逗号在 out 里的下标（后面只跟空白时才算“尾随”）
    for c in text:
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            pending = -1
            out.append(c)
        elif c == ",":
            pending = len(out)
            out.append(c)
        elif c in "}]":
            if pending >= 0:
                out.pop(pending)
                pending = -1
            out.append(c)
        elif c in " \t\r\n":
            out.append(c)
        else:
            pending = -1
            out.append(c)
    return "".join(out)


def load_json(path, default=None):
    """读 JSON 文件；不存在或解析失败返回 default（不抛异常）。"""
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return default


def load_json_tolerant(path, default=None):
    try:
        return tolerant_json(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:  # noqa: BLE001
        return default


def dump_atomic(path, data, indent: int = 2) -> bool:
    """先写临时文件再替换，避免写一半断电/崩溃把配置写坏。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=indent)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return True
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        return False
