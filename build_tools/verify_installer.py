"""校验安装器脚本语法，并模拟安装器的复制/快捷方式/注册表动作。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
OUT = WS / ".build" / "check"
OUT.mkdir(parents=True, exist_ok=True)
PKG = WS / "安装包"


def extract_scripts(hta: Path) -> str:
    text = hta.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", text, re.S | re.I)
    code = "\n".join(blocks)
    # cscript 里没有 window：只把赋值目标换掉，保留函数体，便于纯语法检查
    code = re.sub(r"window\.onload\s*=", "var __onload =", code)
    return code


def main() -> int:
    print("=== 1) 安装器 JScript 语法检查 ===")
    ok = True
    for name in ("安装.hta", "卸载.hta"):
        src = PKG / name if (PKG / name).exists() else WS / "installer" / name
        code = extract_scripts(src)
        js = OUT / (name.replace(".hta", ".js"))
        js.write_text(code, encoding="utf-16")  # 带 BOM，cscript 按 Unicode 读
        proc = subprocess.run(
            ["cscript", "//nologo", "//E:JScript", str(js)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        bad = ("Syntax error" in out) or ("语法错误" in out) or ("编译错误" in out)
        print(f"  {name}: {'语法 OK' if not bad else '语法错误'}")
        if bad:
            ok = False
            print("   ", out[:400])
        elif out:
            print(f"    （运行时提示，属正常：{out.splitlines()[0][:100]}）")
    if not ok:
        return 1

    print("\n=== 2) 快捷方式 + 图标 机制验证 ===")
    sim = OUT / "sim"
    shutil.rmtree(sim, ignore_errors=True)
    sim.mkdir(parents=True)
    install_dir = sim / "StardewModManager"
    # 模拟安装器：把 payload 复制过去，并把 .dat 还原成真名
    src = PKG / "payload" / "StardewModManager"
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = install_dir / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        name = item.name[:-4] if item.name.lower().endswith(".dat") else item.name
        shutil.copy2(item, target.with_name(name))
    exe = install_dir / "StardewModManager.exe"
    icon = install_dir / "icon.ico"
    lnk = sim / "星露谷 Mod 管理器.lnk"
    ps = f"""
$sh = New-Object -ComObject WScript.Shell
$l = $sh.CreateShortcut('{lnk}')
$l.TargetPath = '{exe}'
$l.WorkingDirectory = '{install_dir}'
$l.IconLocation = '{icon},0'
$l.Description = '星露谷 Mod 管理器'
$l.Save()
$c = $sh.CreateShortcut('{lnk}')
"目标   : " + $c.TargetPath
"工作目录: " + $c.WorkingDirectory
"图标   : " + $c.IconLocation
"""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        errors="replace",
    )
    print(proc.stdout.strip())
    if not lnk.exists():
        print("!! 快捷方式没有创建成功")
        print(proc.stderr[:400])
        return 1
    print(f"  快捷方式文件：{lnk.name}（{lnk.stat().st_size} 字节）")
    assert "StardewModManager.exe" in proc.stdout
    assert "icon.ico" in proc.stdout

    print("\n=== 3) 安装后的文件完整性 ===")
    need = ["StardewModManager.exe", "icon.ico", "卸载.hta", "_internal"]
    for n in need:
        p = install_dir / n
        print(f"  {n}: {'OK' if p.exists() else '缺失'}")
        assert p.exists(), n
    total = sum(p.stat().st_size for p in install_dir.rglob("*") if p.is_file())
    print(f"  文件数：{sum(1 for p in install_dir.rglob('*') if p.is_file())}，合计 {total/1048576:.1f} MB")

    print("\n=== 4) 从“安装目录”启动验证 ===")
    import os

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.Popen([str(exe)], cwd=str(install_dir), env=env)
    import time

    time.sleep(10)
    alive = proc.poll() is None
    print(f"  进程存活：{alive}")
    if alive:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    created = (install_dir / "config.json").exists()
    print(f"  已生成 config.json：{created}")
    assert alive and created

    shutil.rmtree(sim, ignore_errors=True)
    print("\nINSTALLER TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
