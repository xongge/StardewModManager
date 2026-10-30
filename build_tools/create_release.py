"""创建 GitHub Release 并上传安装包。

用法：
    set GH_TOKEN=<你的 GitHub token>
    python build_tools/create_release.py

版本号从 app/__init__.py 的 APP_VERSION 自动读取，说明从 CHANGELOG.md 对应段落提取，
附件名统一用 ASCII（StardewModManager-Setup-<版本>.exe），避免中文名被接口弄坏。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
REPO = "xongge/StardewModManager"
EXE = WS / "星露谷Mod管理器-安装程序.exe"
CHANGELOG = WS / "CHANGELOG.md"


def read_version() -> str:
    text = (WS / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("app/__init__.py 里找不到 APP_VERSION")
    return match.group(1)


def read_notes(version: str) -> str:
    """从 CHANGELOG.md 里取当前版本的段落。"""
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(rf"^##\s*v{re.escape(version)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not match:
        return ""
    return f"## 本次更新\n\n{match.group(1).strip()}\n"


FOOTER = """
## 安装

下载下面的 `StardewModManager-Setup-{ver}.exe`，双击即可安装（**不需要 Python，也不需要管理员权限**）。
覆盖安装不会删除你的 `config.json` 与汉化缓存；建议先关掉正在运行的程序。
"""


def api(method: str, url: str, payload: bytes | None = None, ctype: str | None = "application/json"):
    token = os.environ.get("GH_TOKEN", "")
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SDVMM-release")
    if payload is not None and ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        print("缺少 GH_TOKEN 环境变量")
        return 2
    ver = read_version()
    tag = f"v{ver}"
    title = f"星露谷 Mod 管理器 {ver}"
    asset_name = f"StardewModManager-Setup-{ver}.exe"
    body = (read_notes(ver) or f"版本 {ver}") + FOOTER.format(ver=ver)
    print(f"版本 {ver} | tag {tag} | 附件 {asset_name}")

    try:
        release = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
        print("Release 已存在：", release.get("html_url"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print("查询失败：", exc.code, exc.read().decode("utf-8", "ignore")[:300])
            return 3
        payload = json.dumps({
            "tag_name": tag,
            "target_commitish": "main",
            "name": title,
            "body": body,
            "draft": False,
            "prerelease": False,
        }).encode("utf-8")
        release = api("POST", f"https://api.github.com/repos/{REPO}/releases", payload)
        print("已创建 Release：", release.get("html_url"))

    names = [a.get("name") for a in release.get("assets", [])]
    if asset_name in names:
        print("附件已存在，跳过：", asset_name)
    elif EXE.exists():
        size = EXE.stat().st_size
        print(f"上传 {asset_name}（{size / 1048576:.1f} MB）…", flush=True)
        data = EXE.read_bytes()
        url = (f"https://uploads.github.com/repos/{REPO}/releases/{release['id']}"
               f"/assets?name={urllib.parse.quote(asset_name, safe='')}")
        asset = api("POST", url, data, ctype="application/octet-stream")
        print("上传成功：", asset.get("browser_download_url"), asset.get("size"))
    else:
        print("找不到安装包：", EXE)

    final = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    print("附件列表：", [(a["name"], a["size"]) for a in final.get("assets", [])])
    print("RELEASE_URL:", final.get("html_url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
