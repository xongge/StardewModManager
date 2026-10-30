"""修正 v1.4 Release 的附件名（用 ASCII 文件名重传，删除被弄乱的旧附件）。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "xongge/StardewModManager"
TAG = "v1.4"
WS = Path(__file__).resolve().parent.parent
EXE = str(WS / "星露谷Mod管理器-安装程序.exe")
WANT = "StardewModManager-Setup-1.4.exe"


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
        print("缺少 GH_TOKEN")
        return 2
    release = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}")
    print("Release:", release.get("html_url"))
    assets = release.get("assets", [])
    print("现有附件:", [(a["name"], a["size"]) for a in assets])

    for asset in assets:
        if asset["name"] != WANT:
            api("DELETE", f"https://api.github.com/repos/{REPO}/releases/assets/{asset['id']}")
            print("已删除旧附件:", asset["name"])

    names = [a["name"] for a in release.get("assets", []) if a["name"] == WANT]
    if not names:
        size = os.path.getsize(EXE)
        print(f"上传 {WANT}（{size / 1048576:.1f} MB）…", flush=True)
        with open(EXE, "rb") as fh:
            data = fh.read()
        url = (f"https://uploads.github.com/repos/{REPO}/releases/{release['id']}"
               f"/assets?name={urllib.parse.quote(WANT, safe='')}")
        asset = api("POST", url, data, ctype="application/octet-stream")
        print("上传成功:", asset.get("name"), asset.get("size"), asset.get("browser_download_url"))

    final = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}")
    print("最终附件:", [(a["name"], a["size"]) for a in final.get("assets", [])])
    print("RELEASE_URL:", final.get("html_url"))
    print("ASSET_URL:", (final.get("assets") or [{}])[0].get("browser_download_url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
