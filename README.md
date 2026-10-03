# 星露谷 Mod 管理器 (Stardew Valley Mod Manager)

> Windows 上的星露谷物语 **Mod 管理 + 汉化 + 更新 + SMAPI 维护** 一体化工具。
> Python + PySide6 编写，深色界面，中文。

[![version](https://img.shields.io/badge/version-1.3-4cc38a)](https://github.com/xongge/StardewModManager/releases)
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

到 [Releases](https://github.com/xongge/StardewModManager/releases) 下载 `星露谷Mod管理器-安装程序.exe`，
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
python build_tools\fetch_build_deps.py        :: 第一次：下载 PyInstaller / PySide6 等构建依赖
python build_tools\build_exe.py               :: 冻结主程序
python build_tools\build_single_installer.py  :: 生成单文件安装程序
python build_tools\test_setup_exe.py          :: 静默安装端到端测试（可选）
```

产物：`星露谷Mod管理器-安装程序.exe`（约 48 MB，单文件，双击即装）。

安装程序：深色界面 + 程序图标、按分辨率与 DPI 自适应、深色标题栏、进度条与实时日志；
支持命令行静默安装 `--silent "D:\目录" [--no-shortcuts] [--no-launch] [--report out.json]`。
打包时会自动做「出厂体检」：安装包内不允许出现配置、缓存、`.py` 源码、明文密钥与本机路径。

## 发布新版本

1. 改 `app/__init__.py` 里的 `APP_VERSION`
2. 重新打包，在 GitHub 上 `Draft a new release`，**Tag 用 `v1.3`**
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
