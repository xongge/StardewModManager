"""生成「GitHub上传版」：只含源码与必要文件，剔除一切个人数据。

用法： python build_tools/make_github_release.py
产物： 工作目录下的「GitHub上传版」文件夹（里面已包含一键上传脚本）
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
OUT = WS / "GitHub上传版"
REPO = "xongge/StardewModManager"
VER = "1.3"

# 绝不复制的东西（个人数据 / 构建产物 / 缓存 / 二进制）
SKIP_NAMES = {
    "config.json", "config.tmp", "name_map.json", "label_map.json",
    "updates_cache.json", "release_notes_cache.json", "app_update.json",
    "__pycache__", ".pytest_cache", ".build", ".setup-temp", ".setup-test",
    "logs", "backup", "smapi_update", "GitHub上传版", ".git",
}
SKIP_SUFFIXES = (".exe", ".pyc", ".pyo", ".log", ".original", ".bak", ".dat", ".zip")
SKIP_FILES = {
    "restore_smapi_shortcut.ps1", "恢复SMAPI桌面快捷方式.bat", "restore_shortcut.py",
    "修复临时目录并启动安装.bat", "payload.zip",
}

README = """# 星露谷 Mod 管理器 (Stardew Valley Mod Manager)

> Windows 上的星露谷物语 **Mod 管理 + 汉化 + 更新 + SMAPI 维护** 一体化工具。
> Python + PySide6 编写，深色界面，中文。

[![version](https://img.shields.io/badge/version-{ver}-4cc38a)](https://github.com/{repo}/releases)
[![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-5aa9ff)](#)
[![python](https://img.shields.io/badge/python-3.10%2B-ffd166)](#)

## 它做什么

| 页面 | 功能 |
| --- | --- |
| 🧩 **模组管理** | 按分类浏览（全部 / 已启用 / 已停用 / 有问题 / 可更新 / 按类型），勾选即启用停用；搜索、批量操作、详情面板；**双击图形化改 Mod 配置**；一键 **AI 汉化名称**；把中文名写进 `manifest.json`（游戏内显示中文）；检测模组更新 |
| 🖥 **运行控制台** | 把 SMAPI 的 CMD 黑窗集成进应用：彩色分级输出（错误红 / 警告黄）、右上角实时错误与警告计数、一个按钮在「启动 / 停止游戏」间切换、可复制选中内容或一键复制全部 |
| ⬆ **SMAPI 更新** | 读取已安装版本、检查最新版与更新日志、**AI 翻译更新日志**、**一键安装 / 修复 SMAPI**，也可调用官方安装器 |
| ⚙ **设置** | 游戏目录与 Mod 目录、AI 接口（任意 OpenAI 兼容）、Nexus 凭据、颜色自定义、软件自身更新检查 |

特点：

- **控制台不再弹黑窗**：SMAPI 输出被接管，自动识别 UTF-16LE / GBK，不会方框乱码
- **配置就在程序目录**：`config.json` 与 `启动.bat` 放在一起，不用去 `%APPDATA%` 翻
- **停用不删文件**：把 Mod 文件夹移到同级的 `Mods.disabled`
- **写中文名会先备份**：修改 `manifest.json` 前自动存一份 `manifest.json.original`，随时可还原
- **AI 汉化有磁盘缓存**：翻过的不会再请求，模型不可用时自动切换
- **界面**：页面切换淡入、导航高亮滑动、深浅两套配色（含 Windows 标题栏）、颜色可自定义
- **软件自身更新**：读本仓库 Release 检查新版本，弹窗显示更新说明并提供下载

## 下载安装

到 [Releases](https://github.com/{repo}/releases) 下载 `星露谷Mod管理器-安装程序.exe`，
双击即可安装（**不需要 Python，也不需要管理员权限**）。卸载走「程序和功能」或安装目录里的 `卸载.hta`。

## 从源码运行

```bat
pip install -r requirements.txt
python main.py
```

或直接双击 `启动.bat`（会自动装依赖，并用 `pythonw` 无控制台启动）。
要求：Windows 10/11，Python 3.10+。

## 使用步骤

1. 「设置」→ 自动检测游戏目录（只会认**含 `Stardew Valley.exe`** 的真实目录）
2. 「模组管理」→ 重新扫描 → 需要的话点「AI 汉化名称」
3. 「SMAPI 更新」→ 检查更新 → 需要时「一键安装 / 修复 SMAPI」
4. 「运行控制台」→ 启动游戏，右上角看错误 / 警告数

快捷键：`F5` 重新扫描，`Ctrl+1~4` 切换页面。

## 关于 Nexus 更新检测

Nexus 的公开页面有 Cloudflare 保护，匿名请求一律 403，所以需要自己提供凭据（GitHub 来源的 Mod 不需要）：

- **Cookie（免申请）**：浏览器登录 nexusmods.com → `F12` → Network → 刷新 → 任一请求 → 复制请求头里的整行 `Cookie`
  （要含 `cf_clearance` 与 `nexusmods_session`），粘贴到「设置 → 模组更新检测」
- **API Key**：设置里点「打开 API Key 页面」生成一个

设置里有「测试 Nexus 连接」，会明确告诉你成功还是失败（403 被拦 / 401 Key 无效 / 解析不到版本）。

## 自己打包

```bat
python build_tools\\fetch_build_deps.py        :: 第一次：下载 PyInstaller / PySide6 等构建依赖
python build_tools\\build_exe.py               :: 冻结主程序
python build_tools\\build_single_installer.py  :: 生成单文件安装程序
python build_tools\\test_setup_exe.py          :: 静默安装端到端测试（可选）
```

产物：`星露谷Mod管理器-安装程序.exe`（约 48 MB，单文件，双击即装）。

安装程序：深色界面 + 程序图标、按分辨率与 DPI 自适应、深色标题栏、进度条与实时日志；
支持命令行静默安装 `--silent "D:\\目录" [--no-shortcuts] [--no-launch] [--report out.json]`。
打包时会自动做「出厂体检」：安装包内不允许出现配置、缓存、`.py` 源码、明文密钥与本机路径。

## 发布新版本

1. 改 `app/__init__.py` 里的 `APP_VERSION`
2. 重新打包，在 GitHub 上 `Draft a new release`，**Tag 用 `v{ver}`**
3. 把 `星露谷Mod管理器-安装程序.exe` 作为附件上传（程序的「下载最新安装包」会用它）
4. Publish

## 目录结构

```
main.py                          入口
启动.bat                         一键启动（自动装依赖）
app/config.py                    配置读写（DPAPI 加密存密钥）
app/mods.py                      Mod 扫描 / manifest 解析 / 启用停用
app/smapi.py                     SMAPI 版本检测 / 下载 / 一键安装与修复
app/game.py                      游戏目录探测 / 进程运行器 / UTF-16 解码
app/ai.py                        AI 汉化（OpenAI 兼容接口 + 模型回退 + 磁盘缓存）
app/modconfig.py                 读取 Mod 的 config.json 与 i18n
app/updates.py                   模组更新检测（Nexus / GitHub）
app/selfupdate.py                软件自身更新检测
app/icongen.py                   纯 Python 生成图标
app/context.py                   全局上下文与后台扫描线程
app/ui/theme.py                  主题配色与 QSS
app/ui/anim.py                   淡入 / 脉冲 / 导航高亮块
app/ui/main_window.py            主窗口
app/ui/pages/*.py                四个页面与配置编辑器
build_tools/*.py                 打包与测试脚本
installer/setup_app.py           单文件安装程序（tkinter）
installer/卸载.hta               卸载程序
```

## 说明

- 本工具与 ConcernedApe、SMAPI 官方无关联，仅为第三方 Mod 管理工具
- 使用前请自行备份存档与 `Mods` 目录
- 密钥保存在本地，用 Windows DPAPI（绑定当前用户）加密；`config.json` 请勿分享

## License

MIT
"""

GITIGNORE = """# 个人配置与缓存（含游戏路径 / API Key，绝对不要提交）
config.json
config.tmp
name_map.json
label_map.json
updates_cache.json
release_notes_cache.json
app_update.json
nexus_debug.html

# 运行产物
logs/
backup/
smapi_update/
*.log
*.original

# 构建产物
.build/
build/
dist/
*.spec
*.exe
payload.zip
安装包/

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
"""

LICENSE = """MIT License

Copyright (c) 2026 xongge

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

UPLOAD_BAT = """@echo off
rem One-click upload to GitHub. Requires git for Windows.
setlocal
cd /d "%~dp0"
set "REPO=https://github.com/{repo}.git"
set "MSG=chore: release v{ver}"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git not found. Install it first: https://git-scm.com/download/win
  pause
  exit /b 1
)

if not exist ".git" (
  echo === git init ===
  git init
  git branch -M main
)

git config user.name >nul 2>nul || git config user.name "xongge"
git config user.email >nul 2>nul || git config user.email "xongge@users.noreply.github.com"

echo === staging files ===
git add -A
git status --short

echo === commit ===
git commit -m "%MSG%"
if errorlevel 1 echo (nothing new to commit, or commit failed - see message above)

echo === remote ===
git remote remove origin >nul 2>nul
git remote add origin %REPO%

echo === push ===
git push -u origin main
if errorlevel 1 (
  echo.
  echo Remote already has commits. Trying: git pull --rebase origin main ...
  git pull --rebase origin main
  if errorlevel 1 (
    git rebase --abort >nul 2>nul
    echo.
    echo [HINT] Rebase did not work automatically ^(probably conflicting files^).
    echo        If you want THIS folder to fully replace the remote content, run:
    echo            git push -u origin main --force
  ) else (
    git push -u origin main
  )
)
if errorlevel 1 (
  echo.
  echo [HINT] If authentication failed, use a Personal Access Token as the password:
  echo        https://github.com/settings/tokens
)
echo.
echo Done. Open https://github.com/{repo}
pause
"""

CHANGELOG = """# 更新日志

## v1.3

- **软件自身更新**：读本仓库 Release 检查新版本，状态栏一键检查，弹窗显示更新说明与下载入口
- **颜色自定义改进**：新增明亮配色（一键切换，标题栏一起换），按钮改为描边风，配色预览
- **模组列表**：修复切换配色后列表文字颜色不跟随、看不清的问题
- **SMAPI 一键修复更安全**：只补缺失的 .NET 运行时文件，不再覆盖游戏自带文件（之前会导致游戏需要去 Steam 校验）
- **控制台分级更准**：SMAPI 控制台输出没有 ERROR/WARN 前缀，改为按内容与上下文判断，错误标红、警告标黄，计数正确
- **更新检测提速**：12 小时内复用缓存、并发数提高、控制台输出批量刷新
- 修复版本误报（`6.6` 与 `6.6.0` 视为同一版本）
- 原版启动：检测到游戏 exe 被第三方工具替换时，自动改用备份文件启动真正的原版
- SMAPI 更新日志 AI 翻译：有缓存时不再重复消耗额度
- 安装程序：按分辨率 / DPI 自适应、深色标题栏、显示程序图标；不再依赖 `%TEMP%`

## v1.2

- 自动检测软件更新（GitHub Releases）
- 修复若干界面问题

## v1.1

- 单文件安装程序（双击即装，无需 Python）
- 安装程序界面美化：渐变标题区、进度条、实时日志

## v1.0

- 模组分类管理、启用停用、manifest 解析与检查
- 应用内 SMAPI 控制台（彩色分级、错误/警告计数、启动停止）
- SMAPI 版本检测与一键安装 / 修复
- AI 汉化 Mod 名称与配置项
- 图形化编辑 Mod 配置
- 模组更新检测（Nexus / GitHub）
"""

SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "疑似明文 API Key"),
    (re.compile(r"nexusmods_session=[^\"'\s;]{6,}"), "疑似 Nexus Cookie"),
    (re.compile(r"cf_clearance=[^\"'\s;]{6,}"), "疑似 Nexus Cookie"),
    (re.compile(r"SteamLibrary\\steamapps", re.I), "本机 Steam 路径"),
    (re.compile("XLG" + "WY", re.I), "本机工作目录名"),
    (re.compile(r"C:\\Users\\[A-Za-z]", re.I), "本机用户目录"),
]


def keep(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.name in SKIP_FILES:
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return True


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if not keep(item):
            continue
        target = dst / item.name
        if item.is_dir():
            count += copy_tree(item, target)
        else:
            shutil.copy2(item, target)
            count += 1
    return count


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    copied = 0
    for name in ("app", "build_tools", "installer"):
        copied += copy_tree(WS / name, OUT / name)
    for name in ("main.py", "requirements.txt", "icon.ico", "icon.png", "启动.bat"):
        src = WS / name
        if src.exists():
            shutil.copy2(src, OUT / name)
            copied += 1

    files = {
        "README.md": README.format(ver=VER, repo=REPO),
        ".gitignore": GITIGNORE,
        "LICENSE": LICENSE,
        "CHANGELOG.md": CHANGELOG,
        "一键上传到GitHub.bat": UPLOAD_BAT.format(repo=REPO, ver=VER),
    }
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
        copied += 1

    # 体检：确认没有夹带个人数据
    problems = []
    for path in OUT.rglob("*"):
        if not path.is_file():
            continue
        if path.name in ("config.json", "name_map.json", "label_map.json"):
            problems.append(f"不该出现：{path.relative_to(OUT)}")
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"{label}：{path.relative_to(OUT)}")

    print(f"已生成：{OUT}")
    print(f"文件数：{copied}")
    if problems:
        print("\n!! 体检不通过：")
        for p in problems:
            print("   -", p)
        return 1
    print("体检通过：无个人数据、无密钥、无本机路径")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
