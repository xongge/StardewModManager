"""用 GitHub API 创建 v1.4 Release 并上传安装包（token 从环境变量 GH_TOKEN 读取）。"""
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
TITLE = "星露谷 Mod 管理器 v1.4"
WS = Path(__file__).resolve().parent.parent
EXE = str(WS / "星露谷Mod管理器-安装程序.exe")

BODY = """## 本次更新

### 更顺的过渡动画
- **页面切换**：旧页面快照带方向滑出并淡出，新页面同时淡入（前进往左、后退往右）
- **模组列表**：条目高亮改为跟随鼠标**平滑滑动**的动画条，不再是瞬间变色
- 左侧分类列表同样使用滑动高亮；切换 Mod 时详情面板淡入
- **按钮**：悬停时淡入一层淡色（普通绿 / 危险红），按下有轻微压暗回弹
- 设置里的 `animations` 开关现在会真正控制全部动画，关掉即完全无动画

### 其它
- 新增软件自身更新检查（读本仓库 Release）
- 修复：一键修复 SMAPI 会覆盖游戏自带 .NET 运行时的问题（改为只补缺失）
- 修复：控制台错误/警告计数为 0、错误不标红（SMAPI 控制台输出没有 ERROR 前缀，改为按内容分级）
- 修复：`6.6` 与 `6.6.0` 误报更新；原版启动实际带 Mod；翻译重复消耗 token
- 性能：更新检查缓存复用、并发提高、控制台输出批量刷新

## 安装

下载下面的 `星露谷Mod管理器-安装程序.exe`，双击即可安装（**不需要 Python，也不需要管理员权限**）。

覆盖安装不会删除你的 `config.json` 与汉化缓存；建议先关掉正在运行的程序。

完整更新说明见仓库里的 `CHANGELOG.md`。
"""


def api(method: str, url: str, payload: bytes | None = None, ctype: str = "application/json"):
    token = os.environ.get("GH_TOKEN", "")
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SDVMM-release")
    if payload is not None and ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        print("缺少 GH_TOKEN")
        return 2

    release = None
    try:
        release = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}")
        print("Release 已存在：", release.get("html_url"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print("查询失败：", exc.code, exc.read().decode("utf-8", "ignore")[:300])
            return 3
        payload = json.dumps({
            "tag_name": TAG,
            "target_commitish": "main",
            "name": TITLE,
            "body": BODY,
            "draft": False,
            "prerelease": False,
        }).encode("utf-8")
        release = api("POST", f"https://api.github.com/repos/{REPO}/releases", payload)
        print("已创建 Release：", release.get("html_url"))

    asset_names = [a.get("name") for a in release.get("assets", [])]
    fname = os.path.basename(EXE)
    if fname in asset_names:
        print("附件已存在，跳过上传：", fname)
    elif os.path.exists(EXE):
        size = os.path.getsize(EXE)
        print(f"上传附件 {fname}（{size / 1048576:.1f} MB）…", flush=True)
        with open(EXE, "rb") as fh:
            data = fh.read()
        url = (f"https://uploads.github.com/repos/{REPO}/releases/"
               f"{release['id']}/assets?name={urllib.parse.quote(fname)}")
        try:
            asset = api("POST", url, data, ctype="application/octet-stream")
            print("附件上传成功：", asset.get("browser_download_url"), asset.get("size"))
        except urllib.error.HTTPError as exc:
            print("附件上传失败：", exc.code, exc.read().decode("utf-8", "ignore")[:300])
            return 4
    else:
        print("找不到安装包：", EXE)

    print("RELEASE_URL:", release.get("html_url"))
    print("TAG:", release.get("tag_name"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
