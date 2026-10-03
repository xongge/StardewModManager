"""SMAPI 版本检测 / GitHub 最新版查询 / 下载 / 安装与修复。

SMAPI 4.x 是自包含 .NET 应用：官方安装包里的
`internal/windows/install.dat` 就是一份 zip，解压后复制进游戏目录即可，
再把 `Stardew Valley.deps.json` 复制成 `StardewModdingAPI.deps.json`。
本模块自己实现安装，不依赖官方的交互式安装器（也可选择调用官方安装器）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

API_LATEST = "https://api.github.com/repos/Pathoschild/SMAPI/releases/latest"
RELEASES_PAGE = "https://github.com/Pathoschild/SMAPI/releases"
CREATE_NO_WINDOW = 0x08000000

# 自包含 .NET 应用启动所必需的文件（缺失就会出现 hostpolicy.dll 报错）
REQUIRED_FILES = [
    "StardewModdingAPI.exe",
    "StardewModdingAPI.dll",
    "StardewModdingAPI.runtimeconfig.json",
    "hostpolicy.dll",
    "hostfxr.dll",
    "coreclr.dll",
]
REQUIRED_DIRS = ["smapi-internal"]


def _no_window_kwargs():
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": CREATE_NO_WINDOW}
    except Exception:  # noqa: BLE001
        return {}


def installed_version(game_dir) -> str:
    """从 StardewModdingAPI.exe 读取文件版本号。"""
    if not game_dir:
        return ""
    exe = Path(game_dir) / "StardewModdingAPI.exe"
    if not exe.exists():
        return ""
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-Item -LiteralPath '{exe}').VersionInfo.FileVersion",
        ]
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, **_no_window_kwargs()
        ).stdout.strip()
        m = re.match(r"^(\d+(?:\.\d+){1,3})", out or "")
        if m:
            parts = m.group(1).split(".")
            while len(parts) > 3 and parts[-1] == "0":
                parts.pop()
            return ".".join(parts)
    except Exception:  # noqa: BLE001
        pass
    for name in ("smapi-internal/version.txt", "version.txt"):
        p = Path(game_dir) / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:  # noqa: BLE001
                pass
    return ""


def verify_smapi(game_dir) -> dict:
    """检查游戏目录里的 SMAPI 是否完整（缺失即会出现 hostpolicy.dll 之类的启动错误）。"""
    gd = Path(game_dir) if game_dir else None
    result = {"installed": False, "ok": False, "missing": [], "version": "", "game_dir": str(gd or "")}
    if not gd or not gd.is_dir():
        return result
    result["installed"] = (gd / "StardewModdingAPI.exe").exists()
    missing = [n for n in REQUIRED_FILES if not (gd / n).exists()]
    missing += [f"{d}/" for d in REQUIRED_DIRS if not (gd / d).is_dir()]
    result["missing"] = missing
    result["ok"] = not missing
    result["version"] = installed_version(gd)
    return result


# ---------------------------------------------------------------- 更新查询
def _http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "StardewModManager/1.0", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", "replace"))


def pick_installer_asset(assets: list, version: str) -> str:
    """挑官方安装包，优先 `SMAPI-x.y.z-installer.zip`，避开 double-zipped。"""
    want = f"smapi-{version}-installer.zip".lower()
    for a in assets:
        if (a.get("name") or "").lower() == want:
            return a.get("url") or ""
    for a in assets:
        n = (a.get("name") or "").lower()
        if n.endswith("-installer.zip") and "double" not in n:
            return a.get("url") or ""
    for a in assets:
        n = (a.get("name") or "").lower()
        if "installer" in n and n.endswith(".zip") and "double" not in n:
            return a.get("url") or ""
    return ""


def latest_release() -> dict:
    data = _http_json(API_LATEST)
    tag = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    assets = [
        {
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": a.get("size") or 0,
        }
        for a in (data.get("assets") or [])
    ]
    return {
        "version": tag,
        "name": data.get("name") or tag,
        "body": data.get("body") or "",
        "page": data.get("html_url") or RELEASES_PAGE,
        "published": data.get("published_at") or "",
        "assets": assets,
        "installer_url": pick_installer_asset(assets, tag),
    }


def download(url: str, dest: Path, progress=None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "StardewModManager/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    return dest


def extract(zip_path: Path, target_dir: Path) -> Path:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target_dir)
    return target_dir


def find_package_root(path: Path) -> Path:
    """找到解压后的安装包根目录（含 install on Windows.bat 或 internal/windows）。"""
    path = Path(path)
    for cand in [path, *[p for p in path.iterdir() if p.is_dir()]]:
        if (cand / "internal" / "windows").is_dir():
            return cand
    for sub in path.rglob("internal"):
        if (sub / "windows").is_dir():
            return sub.parent
    return path


def find_payload(package_root: Path) -> Path | None:
    p = Path(package_root) / "internal" / "windows" / "install.dat"
    return p if p.exists() else None


RUNTIME_SKIP = ("smapi.installer", "install.dat", "createdump.exe")


def runtime_files(package_root: Path) -> list:
    """自包含 .NET 运行时文件（安装器自己要用的几个文件除外）。"""
    win = Path(package_root) / "internal" / "windows"
    if not win.is_dir():
        return []
    out = []
    for p in win.iterdir():
        if not p.is_file():
            continue
        low = p.name.lower()
        if any(s in low for s in RUNTIME_SKIP):
            continue
        out.append(p)
    return out


def install_from_package(package_root: Path, game_dir, backup_dir: Path | None = None, log=None) -> dict:
    """把安装包内容装进游戏目录（可自动修复缺失的宿主文件）。返回统计信息。"""
    package_root = find_package_root(Path(package_root))
    gd = Path(game_dir)
    if not gd.is_dir():
        raise FileNotFoundError(f"游戏目录不存在：{gd}")
    payload = find_payload(package_root)
    if payload is None:
        raise FileNotFoundError("安装包里没有 internal/windows/install.dat")

    def say(msg):
        if log:
            log(msg)

    # 备份将被覆盖的 SMAPI 自身文件
    backup = None
    if backup_dir:
        backup = Path(backup_dir)
        backup.mkdir(parents=True, exist_ok=True)
        for name in ("StardewModdingAPI.exe", "StardewModdingAPI.dll",
                     "StardewModdingAPI.runtimeconfig.json", "StardewModdingAPI.deps.json",
                     "StardewModdingAPI.exe.config", "smapi-internal"):
            src = gd / name
            if src.exists():
                dest = backup / name
                try:
                    if src.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest, ignore_errors=True)
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
                except Exception as exc:  # noqa: BLE001
                    say(f"[备份] 跳过 {name}：{exc}")
        say(f"[备份] 原文件已备份到 {backup}")

    copied = 0
    kept = 0
    # 1) 运行时文件（hostpolicy.dll / coreclr.dll / System.*.dll 等）
    #    游戏本身自带一套 .NET 运行时，绝对不能覆盖，否则游戏会启动不了
    #    （覆盖后只能去 Steam 校验文件）。这里只补缺失的。
    rt = runtime_files(package_root)
    say(f"[安装] 检查 .NET 运行时文件 {len(rt)} 个（只补缺失的，不覆盖游戏自带文件）…")
    for p in rt:
        dest = gd / p.name
        if dest.exists():
            kept += 1
            continue
        try:
            shutil.copy2(p, dest)
            copied += 1
        except Exception as exc:  # noqa: BLE001
            say(f"[安装] 复制失败 {p.name}：{exc}")
    if kept:
        say(f"[安装] 已保留游戏自带的 {kept} 个运行时文件（未覆盖）")

    # 2) install.dat 里的 SMAPI 本体：只写 SMAPI 自己的文件
    tmp = Path(package_root).parent / "_smapi_payload_tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as zf:
        names = zf.namelist()
        zf.extractall(tmp)
    say(f"[安装] 解压 SMAPI 本体 {len(names)} 项…")

    def allowed(name: str) -> bool:
        low = name.lower()
        return (
            low.startswith("smapi-internal")
            or low.startswith("stardewmoddingapi")
            or low == "steam_appid.txt"
            or low == "mods"
        )

    for item in tmp.iterdir():
        if not allowed(item.name):
            say(f"[安装] 跳过不属于 SMAPI 的文件：{item.name}")
            continue
        target = gd / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for sub in item.rglob("*"):
                rel = sub.relative_to(item)
                dest = target / rel
                if sub.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sub, dest)
                    copied += 1
        else:
            shutil.copy2(item, target)
            copied += 1
    shutil.rmtree(tmp, ignore_errors=True)

    # 3) deps.json
    deps_src = gd / "Stardew Valley.deps.json"
    deps_dst = gd / "StardewModdingAPI.deps.json"
    deps_ok = False
    if deps_src.exists():
        shutil.copy2(deps_src, deps_dst)
        deps_ok = True
        copied += 1
        say("[安装] 已生成 StardewModdingAPI.deps.json")
    else:
        say("[安装] 警告：游戏目录里没有 Stardew Valley.deps.json，跳过 deps 复制")

    state = verify_smapi(gd)
    say(
        f"[安装] 完成：新增/更新 {copied} 个文件，保留原有 {kept} 个；"
        f"完整性检查：{'通过' if state['ok'] else '仍缺少 ' + ', '.join(state['missing'])}"
    )
    return {
        "copied": copied,
        "kept": kept,
        "deps": deps_ok,
        "backup": str(backup) if backup else "",
        "verify": state,
        "package_root": str(package_root),
    }


def build_install_command(package_root: Path, game_dir: str):
    """官方交互式安装器的启动命令（备选方案）。"""
    package_root = find_package_root(Path(package_root))
    exe = package_root / "internal" / "windows" / "SMAPI.Installer.exe"
    if exe.exists():
        args = []
        if game_dir:
            args = ["--game-path", str(game_dir)]
        return str(exe), args, str(package_root)
    bat = None
    for child in package_root.iterdir():
        if child.is_file() and child.name.lower().endswith(".bat"):
            bat = child
            break
    if bat:
        return "cmd", ["/c", str(bat)], str(package_root)
    raise FileNotFoundError("安装包内未找到安装器（internal/windows/SMAPI.Installer.exe）")
