"""打包「单文件安装程序」：一个 exe，双击即可安装。

用法：
    python build_tools/build_single_installer.py [--reuse]

产物：
    星露谷Mod管理器-安装程序.exe        ← 只需这一个文件，发给别人双击即可
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
BUILD = WS / ".build"
LIB = BUILD / "pylibs"
DIST = BUILD / "dist"
APP_DIR = DIST / "StardewModManager"
PKG_WORK = BUILD / "setup"
OUT_EXE = WS / "星露谷Mod管理器-安装程序.exe"

PAYLOAD_NAME = "payload.zip"
BANNED_NAMES = {"config.json", "config.tmp", "name_map.json", "label_map.json",
                "updates_cache.json", "logs", "backup", "smapi_update", "__pycache__"}
BANNED_SUFFIXES = (".original", ".log", ".bak", ".py")
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")


def build_payload_zip() -> Path:
    """把冻结好的程序（排除个人数据）打成 payload.zip。"""
    if not (APP_DIR / "StardewModManager.exe").exists():
        raise SystemExit("还没有冻结好的程序，先运行 build_tools/build_exe.py")
    PKG_WORK.mkdir(parents=True, exist_ok=True)
    target = PKG_WORK / PAYLOAD_NAME
    if target.exists():
        target.unlink()
    staged = PKG_WORK / "staged" / "StardewModManager"
    if staged.parent.exists():
        shutil.rmtree(staged.parent)
    staged.mkdir(parents=True)

    skipped = []

    def copy_tree(src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.iterdir()):
            if item.name in BANNED_NAMES or item.name.endswith(BANNED_SUFFIXES):
                skipped.append(str(item.relative_to(APP_DIR)))
                continue
            if item.is_dir():
                copy_tree(item, dst / item.name)
            else:
                shutil.copy2(item, dst / item.name)

    copy_tree(APP_DIR, staged)
    # 卸载程序一起装进去
    shutil.copy2(WS / "installer" / "卸载.hta", staged / "卸载.hta")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(staged.parent))
    if skipped:
        print("已排除个人数据：" + "、".join(skipped[:6]))
    size = target.stat().st_size
    print(f"payload.zip 生成完毕：{size/1048576:.1f} MB / {len(list(staged.rglob('*')))} 项")
    audit_payload(staged)
    return target


def audit_payload(staged: Path) -> None:
    problems = []
    for path in staged.rglob("*"):
        if not path.is_file():
            continue
        if path.name in BANNED_NAMES or path.suffix.lower() in (".py", ".log"):
            problems.append(f"不该打包：{path.relative_to(staged)}")
            continue
        if path.stat().st_size > 3_000_000:
            continue
        try:
            text = path.read_bytes()[:300_000].decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if SECRET_RE.search(text):
            problems.append(f"疑似含密钥：{path.relative_to(staged)}")
    if problems:
        for p in problems:
            print("  !!", p)
        raise SystemExit("payload 体检不通过，已中止打包")
    print("payload 体检通过：无个人配置、无密钥、无源码")


def build_exe(payload: Path) -> Path:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB)
    env["PYTHONIOENCODING"] = "utf-8"
    version_file = BUILD / "setup_version.txt"
    version_file.write_text(
        """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,3,0,0), prodvers=(1,3,0,0), mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('080404B0', [
    StringStruct('CompanyName', 'Stardew Mod Manager'),
    StringStruct('FileDescription', '星露谷 Mod 管理器 安装程序'),
    StringStruct('FileVersion', '1.3.0.0'),
    StringStruct('InternalName', 'SDVMMSetup'),
    StringStruct('LegalCopyright', 'Copyright (C) 2026 Stardew Mod Manager. All rights reserved.'),
    StringStruct('OriginalFilename', '星露谷Mod管理器-安装程序.exe'),
    StringStruct('ProductName', '星露谷 Mod 管理器 安装程序'),
    StringStruct('ProductVersion', '1.3.0.0')])]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])])
""",
        encoding="utf-8",
    )
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "SDVMMSetup",
        "--icon", str(WS / "icon.ico"),
        "--version-file", str(version_file),
        "--distpath", str(PKG_WORK / "dist"),
        "--workpath", str(PKG_WORK / "work"),
        "--specpath", str(PKG_WORK / "spec"),
        "--runtime-tmpdir", ".",   # 解压到 exe 旁边，避免 %TEMP% 不可写时报
                                     # “Could not create temporary directory!”
        "--add-data", f"{payload};.",
        "--add-data", f"{WS / 'icon.png'};.",
        "--add-data", f"{WS / 'icon.ico'};.",
        "--exclude-module", "PySide6",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
        str(WS / "installer" / "setup_app.py"),
    ]
    print("» 打包单文件安装程序（体积较大，需要一两分钟）…")
    proc = subprocess.run(cmd, cwd=str(WS), env=env)
    if proc.returncode != 0:
        raise SystemExit("PyInstaller 打包失败")
    built = PKG_WORK / "dist" / "SDVMMSetup.exe"
    if not built.exists():
        raise SystemExit("没有生成安装程序 exe")
    return install_output(built)


def audit_exe(exe: Path) -> None:
    """在二进制里直接搜密钥与个人路径，确保没有夹带。"""
    raw = exe.read_bytes()
    checks = {
        "明文 API Key（sk-…）": re.search(rb"sk-[A-Za-z0-9_\-]{16,}", raw) is not None,
        "你的 Steam 游戏路径": b"SteamLibrary\\steamapps" in raw,
        "config.json 内容（ai_key）": b'"ai_key": "sk-' in raw,
    }
    bad = [k for k, v in checks.items() if v]
    for k, v in checks.items():
        print(f"  {k}: {'!! 命中' if v else 'OK 未命中'}")
    if bad:
        raise SystemExit("安装程序里检测到敏感信息，已中止")


def install_output(built: Path) -> Path:
    """把新构建放到正式文件名；如果旧文件正在运行（被占用）就改名让位。"""
    if OUT_EXE.exists():
        try:
            OUT_EXE.unlink()
        except PermissionError:
            bak = OUT_EXE.with_name(OUT_EXE.stem + "-旧版.exe")
            try:
                if bak.exists():
                    bak.unlink()
                OUT_EXE.rename(bak)
                print(f"原安装程序正在运行，已改名为：{bak.name}")
            except Exception:  # noqa: BLE001
                alt = OUT_EXE.with_name(OUT_EXE.stem + "-new.exe")
                shutil.copy2(built, alt)
                print(f"目标文件被占用，本次输出为：{alt.name}")
                return alt
    shutil.copy2(built, OUT_EXE)
    return OUT_EXE


def main() -> int:
    if not LIB.is_dir():
        raise SystemExit("缺少构建依赖，先运行 build_tools/fetch_build_deps.py")
    if "--reuse" in sys.argv:
        payload = PKG_WORK / PAYLOAD_NAME
        if not payload.exists():
            payload = build_payload_zip()
        else:
            print(f"复用已有 {PAYLOAD_NAME}")
    else:
        payload = build_payload_zip()
    exe = build_exe(payload)
    size = exe.stat().st_size
    print(f"\n单文件安装程序：{exe}（{size/1048576:.1f} MB）")
    print("出厂体检：")
    audit_exe(exe)
    print("\n完成：把这一个 exe 发给别人，双击即可安装。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
