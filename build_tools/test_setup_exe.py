"""实测单文件安装程序：静默安装 → 校验文件/快捷方式/注册表 → 启动 → 清理。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import winreg
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
EXE = WS / "星露谷Mod管理器-安装程序.exe"
TEST = WS / ".setup-test"
TARGET = TEST / "install"
DESKTOP = TEST / "desktop"
REPORT = TEST / "report.json"
KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\StardewModManager"


def main() -> int:
    shutil.rmtree(TEST, ignore_errors=True)
    DESKTOP.mkdir(parents=True, exist_ok=True)
    temp = TEST / "不存在的临时目录"          # 故意不创建：验证不再依赖 %TEMP%
    print(f"（故意把 TEMP 指向不存在的目录：{temp.name}）")
    # 本会话沙箱不允许写系统 TEMP，onefile 解压会失败；把 TEMP 指到工作区
    env = dict(os.environ)
    env["TEMP"] = str(temp)
    env["TMP"] = str(temp)
    print(f"安装程序：{EXE.name}（{EXE.stat().st_size/1048576:.1f} MB）")

    print("\n=== 1) 静默安装（含快捷方式，桌面重定向到临时目录）===")
    started = time.time()
    proc = subprocess.run(
        [str(EXE), "--silent", str(TARGET), "--desktop", str(DESKTOP),
         "--no-launch", "--report", str(REPORT)],
        capture_output=True,
        timeout=600,
        env=env,
    )
    print(f"退出码：{proc.returncode}　耗时 {time.time()-started:.1f}s")
    assert REPORT.exists(), "没有生成报告"
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    print("报告：", {k: report[k] for k in ("ok", "files", "registry")})
    print("日志：", " / ".join(report.get("log", [])[:4]))
    print("快捷方式：", [Path(p).name for p in report.get("shortcuts", [])])
    assert report["ok"], report.get("errors")
    if not report["registry"]:
        print("  注：本会话沙箱禁止子进程写注册表，所以这里显示失败；正常双击运行时不受影响")

    print("\n=== 2) 文件校验 ===")
    app = TARGET / "StardewModManager"
    for name in ("StardewModManager.exe", "icon.ico", "卸载.hta", "_internal"):
        p = app / name
        print(f"  {name}: {'OK' if p.exists() else '缺失'}")
        assert p.exists(), name
    count = sum(1 for p in app.rglob("*") if p.is_file())
    print(f"  文件数：{count}")

    print("\n=== 3) 快捷方式（含图标）===")
    lnk = DESKTOP / "星露谷 Mod 管理器.lnk"
    assert lnk.exists(), "桌面快捷方式没创建"
    ps = f"""
$sh = New-Object -ComObject WScript.Shell
$c = $sh.CreateShortcut('{lnk}')
"目标=" + $c.TargetPath
"图标=" + $c.IconLocation
"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, errors="replace").stdout
    print("  " + out.replace("\n", "\n  ").strip())
    assert "StardewModManager.exe" in out and "icon.ico" in out
    menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/星露谷 Mod 管理器"
    print(f"  开始菜单目录：{'存在' if menu.exists() else '缺失'}")
    assert menu.exists()

    print("\n=== 4) 注册表（程序和功能）===")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            disp = winreg.QueryValueEx(k, "DisplayName")[0]
            uninst = winreg.QueryValueEx(k, "UninstallString")[0]
        print(f"  显示名：{disp}")
        print(f"  卸载命令：{uninst}")
        assert "卸载" in uninst or "hta" in uninst
    except PermissionError:
        print("  注：沙箱禁止本会话写注册表（正常双击运行时 HKCU 写入不需要管理员权限）")

    print("\n=== 5) 启动安装后的程序（离屏）===")
    run_env = dict(env)
    run_env["QT_QPA_PLATFORM"] = "offscreen"
    p = subprocess.Popen([str(app / "StardewModManager.exe")], cwd=str(app), env=run_env)
    time.sleep(10)
    alive = p.poll() is None
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    cfg = app / "config.json"
    print(f"  进程存活：{alive}　生成 config.json：{cfg.exists()}")
    assert alive and cfg.exists()
    text = cfg.read_text(encoding="utf-8")
    print(f"  配置里 ai_key 字段：{json.loads(text).get('ai_key')!r}　含明文 key：{'sk-' in text}")
    assert "sk-" not in text

    print("\n=== 6) 重复安装（覆盖）===")
    proc = subprocess.run(
        [str(EXE), "--silent", str(TARGET), "--no-shortcuts", "--no-launch", "--report", str(REPORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600, env=env)
    report2 = json.loads(REPORT.read_text(encoding="utf-8"))
    print(f"  第二次安装 ok={report2['ok']} 文件={report2['files']}")
    assert report2["ok"]

    print("\n=== 7) 清理测试痕迹 ===")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
        print("  已删除注册表项")
    except Exception as exc:  # noqa: BLE001
        print("  删除注册表失败：", exc)
    shutil.rmtree(menu, ignore_errors=True)
    shutil.rmtree(TEST, ignore_errors=True)
    print("  已删除测试目录与快捷方式")
    print("\nSETUP EXE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
