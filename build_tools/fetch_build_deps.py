"""把 PyInstaller 及其依赖 + PySide6 下载到 .build/pylibs（本机 pip 装不了，手动取 wheel）。

用法： python build_tools/fetch_build_deps.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
LIB = WS / ".build" / "pylibs"
WHL = WS / ".build" / "wheels"
LIB.mkdir(parents=True, exist_ok=True)
WHL.mkdir(parents=True, exist_ok=True)

# 包名 -> 需要的模块名（用于校验）
PACKAGES = [
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "packaging",
    "pefile",
    "pywin32-ctypes",
    "setuptools",
    "shiboken6",
    "PySide6-Essentials",
]

PREFER_TAGS = (
    "cp310-abi3-win_amd64",
    "cp39-abi3-win_amd64",
    "py3-none-win_amd64",
    "py3-none-any",
    "py2.py3-none-any",
)


def pick(pkg: str):
    url = f"https://pypi.org/pypi/{pkg}/json"
    with urllib.request.urlopen(url, timeout=90) as r:  # noqa: S310
        data = json.load(r)
    files = data.get("urls") or []
    best = None
    best_rank = 999
    for f in files:
        name = f["filename"]
        if not name.endswith(".whl"):
            continue
        for rank, tag in enumerate(PREFER_TAGS):
            if name.endswith(tag + ".whl") and rank < best_rank:
                best, best_rank = (name, f["url"]), rank
    if best is None:
        # 退一步：任意 wheel
        for f in files:
            if f["filename"].endswith(".whl"):
                best = (f["filename"], f["url"])
                break
    if best is None:
        raise SystemExit(f"找不到 {pkg} 的 wheel")
    return best


def main() -> int:
    for pkg in PACKAGES:
        name, url = pick(pkg)
        dest = WHL / name
        if not dest.exists():
            print(f"下载 {name}", flush=True)
            urllib.request.urlretrieve(url, dest)  # noqa: S310
        print(f"解包 {name}", flush=True)
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(LIB)
    # 让 python 能直接 import
    print(f"\n完成，依赖目录：{LIB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
