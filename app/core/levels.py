"""控制台输出分级：SMAPI 的控制台输出没有 ERROR/WARN 前缀，只能按内容+上下文判断。"""
from __future__ import annotations

import re

LEVEL_RE = re.compile(r"\b(ERROR|ALERT|CRITICAL|FATAL|WARN|WARNING|TRACE|DEBUG)\b")

ERROR_HINTS = (
    "error", "failed", "failure", "exception", "crash", "could not", "cannot ", "can't ",
    "unable to", "not found", "missing", "invalid", "conflict", "denied", "aborted",
    "fatal", "no longer", "incompatible", "unexpected", "not loaded",
)
WARN_HINTS = (
    "warn", "deprecat", "ignored", "skipped", "unsupported", "outdated", "out-of-date",
    "requires smapi", "not compatible", "may not work", "recommend", "but you have",
    "not compatible", "out of date",
)
CONTEXT_BLOCK = (
    "could not be added", "skipped mods", "these mods", "no longer compatible",
    "consider updating", "error log",
)


class LevelTracker:
    """按内容 + 上下文判断一行属于 error / warn / info（有状态）。"""

    def __init__(self) -> None:
        self.context = ""
        self.remain = 0

    def level(self, line: str) -> str:
        text = line or ""
        low = text.lower()
        match = LEVEL_RE.search(text)
        if match:
            lv = match.group(1)
            if lv in ("ERROR", "ALERT", "CRITICAL", "FATAL"):
                return "error"
            if lv in ("WARN", "WARNING"):
                return "warn"
            if lv in ("TRACE", "DEBUG"):
                return "trace"
            return "info"

        stripped = text.strip()
        indented = (
            text.startswith((" ", "\t"))
            or stripped.startswith(("-", "•"))
            or bool(re.match(r"^\[[^\]]+\]\s+[-•]", text))
            or "   " in text[:24]
        )
        if not indented:
            # 新区块开始：清掉上一段上下文，免得把后面的行也染成红色
            self.context = ""
            self.remain = 0
        for key in CONTEXT_BLOCK:
            if key in low:
                self.context = "warn" if key in ("skipped mods", "consider updating") else "error"
                self.remain = 60
                break
        if self.remain > 0 and indented:
            self.remain -= 1
            if self.context:
                return self.context
        if any(h in low for h in ERROR_HINTS):
            return "error"
        if any(h in low for h in WARN_HINTS):
            return "warn"
        return "info"


def classify(line: str) -> str:
    """无状态快速判断（控制台以外的地方用）。"""
    return LevelTracker().level(line)
