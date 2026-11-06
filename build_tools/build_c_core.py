"""编译并测试 C 核心（sdvcore.dll）。

用 zig cc（自带 MinGW 头文件，不需要装 Visual Studio）：
    python build_tools/build_c_core.py [--bench]

产物：
    .build/c/sdvcore.dll     给 Python/其它程序调用的 C 库
    .build/c/test_core.exe   自测程序
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
C_SRC = WS / "csrc" / "sdvcore.c"
C_TEST = WS / "csrc" / "test_core.c"
OUT = WS / ".build" / "c"
ZIG = WS / ".tools" / "zig" / "ziglang" / "zig.exe"


def find_zig() -> Path:
    for cand in (ZIG, *WS.glob(".tools/zig/**/zig.exe")):
        if Path(cand).exists():
            return Path(cand)
    raise SystemExit("找不到 zig.exe，先运行 .tools/fetch_zig.py")


def zig_env() -> dict:
    """zig 默认的缓存/临时目录在本机不可写，统一指到工作区 .build 下。"""
    import os

    env = dict(os.environ)
    cache = WS / ".build" / "zig-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env["ZIG_GLOBAL_CACHE_DIR"] = str(cache / "global")
    env["ZIG_LOCAL_CACHE_DIR"] = str(cache / "local")
    tmp = cache / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    return env


def find_mods_dir():
    """自动找 Mods 目录：环境变量 → 应用配置 → 游戏目录探测。"""
    env = os.environ.get("SDV_MODS_DIR")
    if env:
        return Path(env)
    try:
        sys.path.insert(0, str(WS))
        from app.config import Config

        configured = Config().get("mods_dir")
        if configured:
            return Path(configured)
        from app.game import default_mods_dir, detect_game_dir

        game = detect_game_dir()
        if game:
            return Path(default_mods_dir(game))
    except Exception:  # noqa: BLE001
        pass
    return None


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    kw.setdefault("env", zig_env())
    return subprocess.run(cmd, **kw)


def main() -> int:
    zig = find_zig()
    print("zig:", zig)
    OUT.mkdir(parents=True, exist_ok=True)

    dll = OUT / "sdvcore.dll"
    t0 = time.perf_counter()
    proc = run([str(zig), "cc", "-target", "x86_64-windows-gnu", "-O2", "-shared",
                "-o", str(dll), str(C_SRC)])
    print(f"编译 DLL：{'成功' if proc.returncode == 0 else '失败'}（{time.perf_counter() - t0:.1f}s）")
    if proc.returncode != 0 or not dll.exists():
        return 1
    print("DLL 大小:", f"{dll.stat().st_size / 1024:.0f} KB")

    exe = OUT / "test_core.exe"
    proc = run([str(zig), "cc", "-target", "x86_64-windows-gnu", "-O2",
                "-o", str(exe), str(C_TEST), str(C_SRC)])
    if proc.returncode != 0 or not exe.exists():
        print("自测程序编译失败")
        return 1

    mods = find_mods_dir()
    if not mods or not mods.exists():
        print("跳过运行测试：找不到 Mods 目录（可用环境变量 SDV_MODS_DIR 指定）")
        return 0
    print("\n=== 运行 C 自测 ===", flush=True)
    run([str(exe), str(mods)])
    if "--bench" in sys.argv:
        print("\n=== Python 侧对照（原实现）===", flush=True)
        sys.path.insert(0, str(WS))
        sys.path.insert(0, str(WS / ".build" / "pylibs"))
        from app import mods as modlib  # noqa: E402

        disabled = mods.parent / "Mods.disabled"
        t0 = time.perf_counter()
        scanned = modlib.scan(mods, disabled, "")
        print(f"Python scan(): {len(scanned)} 个，{(time.perf_counter() - t0) * 1000:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
