"""把程序冻结成 exe（PyInstaller），并把结果整理成安装包。

用法： python build_tools/build_exe.py

产物：
    .build/dist/StardewModManager/       ← 冻结后的程序（exe + _internal）
    安装包/                              ← 可直接分享给别人的安装包
        安装.hta
        安装说明.txt
        payload/
            卸载.hta
            StardewModManager/...
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
BUILD = WS / ".build"
LIB = BUILD / "pylibs"
DIST = BUILD / "dist"
WORK = BUILD / "work"
SPEC = BUILD / "spec"
PKG = WS / "安装包"
PAYLOAD_NAME = "StardewModManager"

# PyInstaller 6 已移除 --key 字节码加密（官方 PR #6999），
# 现在用「编译成机器码」的 Nuitka 才是真正提升破解难度的做法，
# 见 build_tools/build_nuitka.py；这里保持 --optimize 2 去掉文档字符串。
VERSION_INFO = '''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 3, 0, 0), prodvers=(1, 3, 0, 0), mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', 'Stardew Mod Manager'),
        StringStruct('FileDescription', '星露谷 Mod 管理器'),
        StringStruct('FileVersion', '1.3.0.0'),
        StringStruct('InternalName', 'StardewModManager'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026 Stardew Mod Manager. All rights reserved.'),
        StringStruct('OriginalFilename', 'StardewModManager.exe'),
        StringStruct('ProductName', '星露谷 Mod 管理器'),
        StringStruct('ProductVersion', '1.3.0.0')])]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
'''

EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "test",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSvgWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtNfc",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
]


def run(cmd, cwd=None, env=None):
    print("»", " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, cwd=cwd, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"命令失败（{proc.returncode}）")


def freeze() -> Path:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB)
    env["PYTHONIOENCODING"] = "utf-8"
    for name in ("spec", "work", "dist"):
        (BUILD / name).mkdir(parents=True, exist_ok=True)
    # 先清掉旧产物，避免混入上次的内容
    out = DIST / PAYLOAD_NAME
    if out.exists():
        shutil.rmtree(out)
    version_file = BUILD / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(VERSION_INFO, encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        PAYLOAD_NAME,
        "--icon",
        str(WS / "icon.ico"),
        "--version-file",
        str(version_file),
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(SPEC),
        "--optimize",
        "2",
        "--hidden-import",
        "app.icongen",
    ]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    cmd.append(str(WS / "main.py"))
    run(cmd, cwd=str(WS), env=env)
    if not (out / f"{PAYLOAD_NAME}.exe").exists():
        raise SystemExit("PyInstaller 没有生成 exe")
    # 图标放到 exe 旁边，方便用户替换 / 快捷方式取图标
    shutil.copy2(WS / "icon.ico", out / "icon.ico")
    shutil.copy2(WS / "icon.png", out / "icon.png")
    return out


# 打包时绝对不能带上的东西（配置、缓存、日志、备份…），
# 免得把你的游戏路径 / API Key / 汉化缓存一起发给别人。
EXCLUDE_NAMES = {
    "config.json",
    "config.tmp",
    "name_map.json",
    "label_map.json",
    "updates_cache.json",
    "logs",
    "backup",
    "smapi_update",
    "__pycache__",
    ".pytest_cache",
}
EXCLUDE_SUFFIXES = (".original", ".origin", ".log", ".bak")

# 安装包里不保留可执行/可运行的原名，避免有人直接在包里运行导致配置落进包里
HIDE_AS_DAT = ("StardewModManager.exe", "卸载.hta")

# 出厂体检：这些文件绝不允许出现在安装包里
BANNED_NAMES = {
    "config.json",
    "config.tmp",
    "name_map.json",
    "label_map.json",
    "updates_cache.json",
}
BANNED_SUFFIXES = (".py", ".log", ".pyw")
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")


def audit_package(pkg: Path) -> list:
    """检查安装包里是否夹带了个人数据 / 密钥 / 源码。"""
    problems = []
    for path in pkg.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(pkg)
        if path.name in BANNED_NAMES or path.suffix.lower() in BANNED_SUFFIXES:
            problems.append(f"不该打包的文件：{rel}")
            continue
        if path.stat().st_size > 3_000_000:
            continue  # 大文件（DLL/EXE）不逐字节扫描
        try:
            text = path.read_bytes()[:400_000].decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if SECRET_RE.search(text):
            problems.append(f"疑似包含 API Key：{rel}")
        if "\\StardewModManager\\config.json" in text and path.name not in (
            "安装说明.txt",
            "MANIFEST.txt",
        ):
            problems.append(f"疑似包含本机配置路径：{rel}")
    return problems


def copy_clean(src: Path, dst: Path) -> int:
    """只复制程序本体，跳过个人数据文件。"""
    dst.mkdir(parents=True, exist_ok=True)
    skipped = 0
    for item in sorted(src.iterdir()):
        name = item.name
        if name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIXES):
            skipped += 1
            print(f"  跳过（个人数据/缓存）：{name}")
            continue
        target = dst / name
        if item.is_dir():
            skipped += copy_clean(item, target)
        else:
            shutil.copy2(item, target)
    return skipped


def build_package(app_dir: Path) -> Path:
    if PKG.exists():
        shutil.rmtree(PKG)
    payload = PKG / "payload"
    payload.mkdir(parents=True)
    print("复制程序文件（自动排除个人数据）…")
    skipped = copy_clean(app_dir, payload / PAYLOAD_NAME)
    if skipped:
        print(f"共跳过 {skipped} 项个人数据")
    # 卸载程序放进安装目录
    shutil.copy2(WS / "installer" / "卸载.hta", payload / PAYLOAD_NAME / "卸载.hta")
    # 安装器
    shutil.copy2(WS / "installer" / "安装.hta", PKG / "安装.hta")
    shutil.copy2(WS / "installer" / "安装说明.txt", PKG / "安装说明.txt")

    # 把可直接运行的东西改名成 .dat：防止有人直接在安装包里双击运行，
    # 那样程序会在 payload 目录里生成 config.json（含密钥/缓存），转发出去就泄漏了。
    hidden = []
    for name in HIDE_AS_DAT:
        src = payload / PAYLOAD_NAME / name
        if src.exists():
            src.rename(src.with_name(name + ".dat"))
            hidden.append(name)
    if hidden:
        print(f"已把 {('、'.join(hidden))} 改名为 .dat（安装时自动还原）")

    # 清单（不含任何个人信息）
    lines = ["星露谷 Mod 管理器 安装包", f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    total = 0
    for p in sorted(payload.rglob("*")):
        if p.is_file():
            size = p.stat().st_size
            total += size
            lines.append(f"{size:>12,}  {p.relative_to(PKG)}")
    lines.append("")
    lines.append(f"合计 {total:,} 字节（{total / 1048576:.1f} MB）")
    (PKG / "MANIFEST.txt").write_text("\n".join(lines), encoding="utf-8")

    # 出厂体检：确认没有夹带任何个人数据 / 密钥
    problems = audit_package(PKG)
    if problems:
        print("\n!! 打包体检不通过：")
        for item in problems:
            print("   -", item)
        raise SystemExit("安装包里发现了不该有的东西，已中止")
    print("打包体检通过：无个人配置、无密钥、无源码")
    return PKG


def main() -> int:
    if not LIB.is_dir():
        raise SystemExit("缺少构建依赖，先运行 build_tools/fetch_build_deps.py")
    reuse = "--reuse" in sys.argv
    app_dir = DIST / PAYLOAD_NAME
    if reuse and (app_dir / f"{PAYLOAD_NAME}.exe").exists():
        print(f"复用已有构建：{app_dir}")
    else:
        app_dir = freeze()
    size = sum(p.stat().st_size for p in app_dir.rglob("*") if p.is_file())
    print(f"\n冻结完成：{app_dir}（{size / 1048576:.1f} MB）")
    # 只做 exe 安装程序时不需要老的 HTA 文件夹版；要生成就加 --with-hta
    if "--with-hta" in sys.argv:
        pkg = build_package(app_dir)
        print(f"HTA 版安装包已生成：{pkg}")
    else:
        print("（未生成 HTA 文件夹版安装包；需要的话加 --with-hta）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
