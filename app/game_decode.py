from __future__ import annotations

"""SMAPI 控制台输出的解码（UTF-16LE / BOM / 本地代码页自适应）。"""
import codecs
import os
import re
import sys

def system_codec() -> str:
    """当前系统的 ANSI 代码页名（中文 Windows 上是 cp936）。"""
    try:
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetACP()}"
    except Exception:  # noqa: BLE001
        return "mbcs"


def decode_line(raw: bytes, prefer: str | None = None) -> tuple:
    """智能解码一行输出：优先 UTF-8，失败则用系统 ANSI 代码页。返回 (文本, 使用的编码)。"""
    for codec in ([prefer] if prefer else []) + ["utf-8", system_codec(), "gbk", "cp1252"]:
        if not codec:
            continue
        try:
            return raw.decode(codec), codec
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


class LineDecoder:
    """把子进程的原始字节切成文本行。

    SMAPI（.NET 控制台程序）在输出被重定向时会写 **UTF-16LE**，
    直接按 UTF-8 解会得到 “S M A P I” 这种夹着 \\x00 的乱码（显示成方框、复制出来也是乱的）。
    这里自动识别 UTF-16LE / UTF-16BE（含 BOM）与本地代码页（中文 Windows 的 GBK）。
    """

    def __init__(self) -> None:
        self.codec: str | None = None   # None=未判定；'utf-16-le'/'utf-16-be'/'text'
        self.buf = bytearray()
        self.text = ""

    # ---------------- 编码判定
    def _detect(self, force: bool = False) -> None:
        data = bytes(self.buf)
        if len(data) >= 2:
            if data[:2] == b"\xff\xfe":
                self.codec = "utf-16-le"
                del self.buf[:2]
                return
            if data[:2] == b"\xfe\xff":
                self.codec = "utf-16-be"
                del self.buf[:2]
                return
        if not data:
            return
        if len(data) < 4 and not force:
            return
        sample = data[:256]
        nuls = sample.count(0)
        if nuls and nuls >= max(1, len(sample) // 4):
            even = sum(1 for i in range(0, len(sample) - 1, 2) if sample[i] == 0)
            odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
            self.codec = "utf-16-be" if even > odd else "utf-16-le"
            return
        self.codec = "text"

    # ---------------- 输入
    def feed(self, data: bytes) -> list:
        self.buf += data
        if self.codec is None:
            self._detect()
            if self.codec is None:
                return []
        if self.codec in ("utf-16-le", "utf-16-be"):
            usable = len(self.buf) - (len(self.buf) % 2)
            if usable <= 0:
                return []
            self.text += bytes(self.buf[:usable]).decode(self.codec, "replace")
            del self.buf[:usable]
        else:
            while True:
                idx = self.buf.find(b"\n")
                if idx < 0:
                    break
                raw = bytes(self.buf[:idx])
                del self.buf[: idx + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                line, _ = decode_line(raw)
                self.text += line + "\n"
        return self._pop_lines()

    def flush(self) -> list:
        self._detect(force=True)
        if self.buf:
            if self.codec in ("utf-16-le", "utf-16-be"):
                self.text += bytes(self.buf).decode(self.codec, "replace")
            else:
                line, _ = decode_line(bytes(self.buf))
                self.text += line
            self.buf.clear()
        out = self._pop_lines()
        if self.text:
            out.append(self.text.rstrip("\r"))
            self.text = ""
        return out

    def _pop_lines(self) -> list:
        out = []
        while "\n" in self.text:
            line, self.text = self.text.split("\n", 1)
            out.append(line.rstrip("\r"))
        return out
