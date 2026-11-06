"""统一 HTTP 层：请求、取 JSON、下载文件（带重试与进度）。

之前三个模块各写了一份 urllib 代码，这里收敛成一份，行为保持一致：
- 统一 User-Agent；可覆盖
- 超时、瞬时错误小退避重试
- 下载支持进度回调与中途取消
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "StardewModManager/1.0"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class HttpError(RuntimeError):
    """HTTP 层错误（网络 / 状态码 / 解析）。"""

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def request(url: str, headers: dict | None = None, data: bytes | None = None,
            timeout: int = 25, retries: int = 1, method: str | None = None) -> bytes:
    """发一个请求，返回响应体原始字节。"""
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            # 4xx 是请求本身的问题，重试没意义
            if 400 <= exc.code < 500:
                raise HttpError(f"HTTP {exc.code} {body}".strip(), exc.code, body) from exc
            last = HttpError(f"HTTP {exc.code} {body}".strip(), exc.code, body)
        except Exception as exc:  # noqa: BLE001
            last = exc
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    if isinstance(last, HttpError):
        raise last
    raise HttpError(str(last) if last else "网络错误")


def fetch_text(url: str, headers: dict | None = None, timeout: int = 25,
               retries: int = 1, encoding: str = "utf-8") -> str:
    return request(url, headers=headers, timeout=timeout, retries=retries).decode(encoding, "replace")


def fetch_json(url: str, headers: dict | None = None, timeout: int = 25, retries: int = 1):
    hdrs = {"Accept": "application/json"}
    hdrs.update(headers or {})
    text = fetch_text(url, headers=hdrs, timeout=timeout, retries=retries)
    try:
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(f"返回内容不是 JSON：{text[:120]}") from exc


def download(url: str, dest, progress=None, should_stop=None,
             timeout: int = 60, chunk: int = 262144, headers: dict | None = None) -> Path:
    """下载到 dest，progress(got, total) 可为 None；should_stop() 返回 True 则中止。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    got = 0
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            with open(dest, "wb") as fh:
                while True:
                    if should_stop is not None and should_stop():
                        raise HttpError("已取消下载")
                    block = resp.read(chunk)
                    if not block:
                        break
                    fh.write(block)
                    got += len(block)
                    if progress is not None:
                        try:
                            progress(got, total)
                        except Exception:  # noqa: BLE001
                            pass
    except HttpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HttpError(f"下载失败：{exc}") from exc
    if total and got < total:
        raise HttpError(f"下载不完整（{got}/{total} 字节）")
    return dest
