"""单文件安装程序：双击这一个 exe 就能安装，不需要 Python、不需要额外文件。

- 程序本体打包在 exe 内部的 payload.zip 里，运行时解压到安装目录；
- 深色界面，可选桌面 / 开始菜单快捷方式、安装后启动；
- 注册到「程序和功能」，卸载走安装目录里的 卸载.hta；
- 支持命令行静默安装（自己用或批量部署）：
      安装程序.exe --silent "D:\\目标目录" [--no-shortcuts] [--no-launch] [--report out.json]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

APP_NAME = "星露谷 Mod 管理器"
APP_VER = "1.3"
FOLDER = "StardewModManager"
EXE_NAME = "StardewModManager.exe"
UNINSTALL_REL = "卸载.hta"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\StardewModManager"

BG = "#12161d"
BG2 = "#171c25"
PANEL = "#1b212c"
LINE = "#2c3542"
TEXT = "#d6deeb"
MUTED = "#8895a7"
ACCENT = "#4cc38a"
ACCENT2 = "#2f9e6b"
RED = "#ff6b6b"

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- 基础
def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def payload_zip() -> Path:
    return bundle_dir() / "payload.zip"


def default_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / FOLDER


def run_hidden(cmd) -> int:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60
        )
        return proc.returncode
    except Exception:  # noqa: BLE001
        return -1


def _ps(value: str) -> str:
    """PowerShell 单引号字符串转义。"""
    return str(value).replace("'", "''")


def make_shortcut_script(entries: list) -> Path:
    """生成临时 PowerShell 脚本创建快捷方式（对中文路径最稳）。

    第一行设 ErrorActionPreference=Stop：这样任何一条快捷方式失败都会让
    退出码非 0，安装程序才能如实提示，而不是假装成功。
    """
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$sh = New-Object -ComObject WScript.Shell",
    ]
    for lnk, target, workdir, icon in entries:
        lines += [
            f"$l = $sh.CreateShortcut('{_ps(lnk)}')",
            f"$l.TargetPath = '{_ps(target)}'",
            f"$l.WorkingDirectory = '{_ps(workdir)}'",
            f"$l.IconLocation = '{_ps(icon)},0'",
            f"$l.Description = '{_ps(APP_NAME)}'",
            "$l.WindowStyle = 1",
            "$l.Save()",
        ]
    tmp = Path(os.environ.get("TEMP") or ".") / "sdvmm_shortcut.ps1"
    tmp.write_text("\r\n".join(lines), encoding="utf-8-sig")
    return tmp


def run_shortcut_script(script: Path) -> int:
    return run_hidden([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script),
    ])


def desktop_dir(override: str | None = None) -> Path:
    if override:
        return Path(override)
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)  # CSIDL_DESKTOP
        if buf.value:
            return Path(buf.value)
    except Exception:  # noqa: BLE001
        pass
    return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def write_registry(target: Path) -> bool:
    try:
        import winreg

        exe = target / FOLDER / EXE_NAME
        icon = target / FOLDER / "icon.ico"
        uninst = target / FOLDER / UNINSTALL_REL
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            def s(name, value):
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

            def d(name, value):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))

            s("DisplayName", APP_NAME)
            s("DisplayVersion", APP_VER)
            s("Publisher", "Stardew Mod Manager")
            s("InstallLocation", str(target))
            s("DisplayIcon", str(icon if icon.exists() else exe))
            s("UninstallString", f'mshta.exe "{uninst}"')
            d("NoModify", 1)
            d("NoRepair", 1)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 安装逻辑
def perform_install(target: Path, shortcuts: bool = True, launch: bool = False,
                    desktop_override: str | None = None, log=print, progress=None) -> dict:
    result = {"ok": False, "target": str(target), "files": 0, "shortcuts": [],
              "registry": False, "errors": [], "warnings": []}
    target.mkdir(parents=True, exist_ok=True)
    src = payload_zip()
    if not src.exists():
        result["errors"].append(f"安装包损坏：找不到 {src.name}")
        return result
    try:
        with zipfile.ZipFile(src) as zf:
            items = zf.infolist()
            total = max(1, len(items))
            locked = []
            for i, item in enumerate(items, 1):
                dest = target / item.filename
                for attempt in range(3):
                    try:
                        zf.extract(item, target)
                        result["files"] += 1
                        break
                    except PermissionError:
                        # 覆盖安装时旧程序可能还占着文件：重试几次，仍失败就跳过
                        if attempt < 2:
                            time.sleep(0.4)
                            continue
                        if dest.exists():
                            locked.append(item.filename)
                        else:
                            raise
                    except Exception:
                        if attempt < 2:
                            time.sleep(0.3)
                            continue
                        raise
                if progress and (i % 4 == 0 or i == total):
                    progress(i / total, f"正在写入文件 {i}/{total}")
        log(f"程序文件写入完成：{result['files']} 个")
        if locked:
            msg = (f"有 {len(locked)} 个文件被占用未覆盖（程序可能还在运行）："
                   + "、".join(locked[:3]))
            result["warnings"].append(msg)
            log(msg)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"解压失败：{exc}")
        return result

    exe = target / FOLDER / EXE_NAME
    icon = target / FOLDER / "icon.ico"
    if not exe.exists():
        result["errors"].append("解压后没有找到主程序 exe")
        return result
    result["ok"] = True  # 程序文件已经装好，后面的快捷方式/注册表失败只算警告

    if shortcuts:
        entries = []
        d = desktop_dir(desktop_override)
        if d.is_dir() or desktop_override:
            d.mkdir(parents=True, exist_ok=True)
            entries.append((str(d / f"{APP_NAME}.lnk"), str(exe), str(exe.parent), str(icon)))
        menu = start_menu_dir() / APP_NAME
        menu.mkdir(parents=True, exist_ok=True)
        entries.append((str(menu / f"{APP_NAME}.lnk"), str(exe), str(exe.parent), str(icon)))
        entries.append(
            (str(menu / f"卸载 {APP_NAME}.lnk"), str(target / FOLDER / UNINSTALL_REL),
             str(exe.parent), str(icon))
        )
        if entries:
            try:
                script = make_shortcut_script(entries)
                code = run_shortcut_script(script)
                if code == 0:
                    result["shortcuts"] = [e[0] for e in entries]
                    log(f"已创建 {len(entries)} 个快捷方式")
                else:
                    result["warnings"].append(f"创建快捷方式失败（PowerShell 返回 {code}）")
                try:
                    script.unlink()
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001
                result["warnings"].append(f"创建快捷方式失败：{exc}")

    result["registry"] = write_registry(target)
    if result["registry"]:
        log("已注册到「程序和功能」")
    else:
        result["warnings"].append("注册表写入失败（不影响使用，可直接运行安装目录里的 卸载.hta）")

    if launch:
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
            log("已启动程序")
        except Exception as exc:  # noqa: BLE001
            result["warnings"].append(f"启动失败：{exc}")

    return result


# ---------------------------------------------------------------- 静默安装
def silent_main(args) -> int:
    target = Path(args.silent).expanduser().resolve()
    lines = []

    def log(msg):
        lines.append(str(msg))

    result = perform_install(
        target,
        shortcuts=not args.no_shortcuts,
        launch=not args.no_launch,
        desktop_override=args.desktop,
        log=log,
    )
    result["log"] = lines
    if args.report:
        try:
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------- Windows 外观
def enable_dpi_awareness() -> None:
    """让窗口在缩放屏（125%/150%）上不糊、不错位。必须在创建窗口前调用。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # per-monitor DPI aware
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def toplevel_hwnd(root) -> int:
    """拿到 Tk 顶层窗口的 HWND（winfo_id 是子窗口，需要取父）。"""
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        return int(hwnd or root.winfo_id())
    except Exception:  # noqa: BLE001
        return 0


def dark_titlebar(root, caption: str = BG2, border: str = LINE, text: str = TEXT) -> bool:
    """把 Windows 原生标题栏改成深色（和主程序一致）。"""
    hwnd = toplevel_hwnd(root)
    if not hwnd:
        return False
    try:
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            if dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break

        def set_color(attr: int, hexcolor: str) -> None:
            r = int(hexcolor[1:3], 16)
            g = int(hexcolor[3:5], 16)
            b = int(hexcolor[5:7], 16)
            ref = ctypes.c_uint(r | (g << 8) | (b << 16))  # COLORREF = 0x00BBGGRR
            try:
                dwm.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                    ctypes.byref(ref), ctypes.sizeof(ref)
                )
            except Exception:  # noqa: BLE001
                pass

        set_color(35, caption)  # DWMWA_CAPTION_COLOR
        set_color(34, border)   # DWMWA_BORDER_COLOR
        set_color(36, text)     # DWMWA_TEXT_COLOR
        return True
    except Exception:  # noqa: BLE001
        return False


def set_window_icon(root) -> bool:
    """设置窗口/任务栏图标（exe 内嵌的 icon.ico / icon.png）。"""
    ok = False
    ico = bundle_dir() / "icon.ico"
    png = bundle_dir() / "icon.png"
    try:
        if ico.exists():
            root.iconbitmap(default=str(ico))
            ok = True
    except Exception:  # noqa: BLE001
        pass
    try:
        if png.exists():
            import tkinter as tk

            img = tk.PhotoImage(file=str(png))
            root.iconphoto(True, img)
            root._icon_photo = img  # 防止被回收
            ok = True
    except Exception:  # noqa: BLE001
        pass
    return ok


def ui_scale(root) -> float:
    """按系统 DPI 算缩放系数，保证高分屏下文字大小合适。"""
    try:
        return max(1.0, min(2.0, float(root.winfo_fpixels("1i")) / 96.0))
    except Exception:  # noqa: BLE001
        return 1.0


# ---------------------------------------------------------------- 图形界面
def gui_main(args) -> int:
    enable_dpi_awareness()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} 安装程序 v{APP_VER}")
    root.configure(bg=BG)
    s = ui_scale(root)
    px = lambda v: max(1, int(round(v * s)))  # noqa: E731

    # 窗口大小按屏幕算，自适应小屏与高分屏
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w = min(px(780), int(sw * 0.66))
    win_h = min(px(620), int(sh * 0.78))
    root.geometry(f"{win_w}x{win_h}+{(sw - win_w)//2}+{max(0, (sh - win_h)//2 - px(30))}")
    root.minsize(px(600), px(470))
    root.resizable(True, True)

    font_title = ("Microsoft YaHei UI", int(16 * s), "bold")
    font_sub = ("Microsoft YaHei UI", int(10 * s))
    font_body = ("Microsoft YaHei UI", int(11 * s))
    font_hint = ("Microsoft YaHei UI", int(9 * s))
    font_mono = ("Consolas", int(9 * s))

    # ---- 顶部：渐变 + 图标 + 标题（用 Canvas 自己画，避免土味标题栏）
    head_h = px(94)
    head = tk.Canvas(root, height=head_h, highlightthickness=0, bg=BG2)
    head.pack(fill="x")
    for i in range(head_h):
        t = i / max(1, head_h - 1)
        r = int(0x17 + (0x1f - 0x17) * t)
        g = int(0x1c + (0x2a - 0x1c) * t)
        b = int(0x25 + (0x38 - 0x25) * t)
        head.create_line(0, i, win_w, i, fill=f"#{r:02x}{g:02x}{b:02x}")
    head.create_line(0, head_h - 2, win_w, head_h - 2, fill=ACCENT2, width=2)
    try:
        icon_src = tk.PhotoImage(file=str(bundle_dir() / "icon.png"))
        factor = max(1, icon_src.width() // px(60))
        icon_small = icon_src.subsample(factor, factor)
        head._icon = icon_small
        head.create_image(px(22), head_h // 2, image=icon_small, anchor="w")
        text_x = px(22) + icon_small.width() + px(14)
    except Exception:  # noqa: BLE001
        text_x = px(24)
    head.create_text(text_x, head_h // 2 - px(12), anchor="w", text=APP_NAME,
                     fill=ACCENT, font=font_title)
    head.create_text(text_x, head_h // 2 + px(14), anchor="w",
                     text=f"安装程序 v{APP_VER} · 目标电脑无需安装 Python",
                     fill=MUTED, font=font_hint)

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=px(20), pady=px(12))

    def flat_button(parent, text, command, primary=False, width_chars=None):
        normal = ACCENT2 if primary else "#202836"
        hover = ACCENT if primary else "#2b3646"
        fg = "#05130c" if primary else TEXT
        btn = tk.Button(
            parent, text=text, command=command, font=font_body, relief="flat", bd=0,
            bg=normal, fg=fg, activebackground=hover, activeforeground=fg,
            padx=px(16), pady=px(7), cursor="hand2", highlightthickness=0,
        )
        if width_chars:
            btn.configure(width=width_chars)
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=normal))
        return btn

    # ---- 第一步
    step1 = tk.Frame(body, bg=BG)
    step1.pack(fill="both", expand=True)

    tk.Label(step1, text="选择安装位置", font=font_body, bg=BG, fg=TEXT).pack(anchor="w")
    dirbox = tk.Frame(step1, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    dirbox.pack(fill="x", pady=(px(6), px(12)))
    dir_var = tk.StringVar(value=str(default_dir()))
    entry = tk.Entry(dirbox, textvariable=dir_var, font=font_body, bg=BG2, fg=TEXT,
                     insertbackground=TEXT, relief="flat", bd=px(8))
    entry.pack(side="left", fill="x", expand=True, padx=(px(6), px(4)), pady=px(6))

    def browse():
        chosen = filedialog.askdirectory(title="选择安装位置",
                                         initialdir=dir_var.get() or str(Path.home()))
        if chosen:
            dir_var.set(chosen)

    flat_button(dirbox, "浏览…", browse).pack(side="right", padx=px(6), pady=px(6))

    tk.Label(step1, text="安装选项", font=font_body, bg=BG, fg=TEXT).pack(anchor="w")
    opt = tk.Frame(step1, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    opt.pack(fill="x", pady=(px(6), px(12)))
    v_desktop, v_menu, v_launch = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    for text, var in (("创建桌面快捷方式（带程序图标）", v_desktop),
                      ("创建开始菜单项", v_menu),
                      ("安装完成后立即启动", v_launch)):
        tk.Checkbutton(opt, text=text, variable=var, font=font_body, bg=PANEL, fg=TEXT,
                       selectcolor=BG2, activebackground=PANEL, activeforeground=TEXT,
                       highlightthickness=0, anchor="w").pack(anchor="w", padx=px(10), pady=px(4))

    tk.Label(step1, text="说明", font=font_body, bg=BG, fg=TEXT).pack(anchor="w")
    tk.Label(
        step1,
        text=("· 默认装到当前用户目录，不需要管理员权限\n"
              "· 配置、汉化缓存都保存在安装目录里，卸载会一并删除\n"
              "· 卸载：控制面板「程序和功能」，或运行安装目录里的 卸载.hta\n"
              "· 本程序为编译打包版本，不含源代码文件"),
        font=font_hint, bg=BG, fg=MUTED, justify="left",
    ).pack(anchor="w", pady=(px(6), 0))

    # ---- 第二步
    step2 = tk.Frame(body, bg=BG)
    top2 = tk.Frame(step2, bg=BG)
    top2.pack(fill="x")
    tk.Label(top2, text="正在安装", font=font_body, bg=BG, fg=TEXT).pack(side="left")
    now = tk.Label(top2, text="准备中…", font=font_hint, bg=BG, fg=MUTED)
    now.pack(side="right")
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    style.configure("Dark.Horizontal.TProgressbar", troughcolor=BG2, background=ACCENT2,
                    bordercolor=LINE, lightcolor=ACCENT2, darkcolor=ACCENT2,
                    thickness=px(14))
    bar = ttk.Progressbar(step2, style="Dark.Horizontal.TProgressbar", maximum=100)
    bar.pack(fill="x", pady=(px(8), 0))
    logbox = tk.Text(step2, height=10, bg=BG2, fg="#a9b6c6", font=font_mono, relief="flat",
                     insertbackground=TEXT, wrap="word", padx=px(8), pady=px(6))
    logbox.pack(fill="both", expand=True, pady=(px(10), 0))
    logbox.configure(state="disabled")

    # ---- 第三步
    step3 = tk.Frame(body, bg=BG)
    tk.Label(step3, text="安装完成", font=font_body, bg=BG, fg=TEXT).pack(anchor="w")
    done_text = tk.Label(step3, text="", font=font_hint, bg=BG, fg=MUTED,
                         justify="left", wraplength=win_w - px(60))
    done_text.pack(anchor="w", pady=(px(8), 0), fill="x")
    step3.bind("<Configure>", lambda e: done_text.configure(wraplength=max(200, e.width - px(10))))

    # ---- 底部
    foot = tk.Frame(root, bg=BG2)
    foot.pack(fill="x", side="bottom")
    foot.configure(height=px(64))
    foot.pack_propagate(False)
    status = tk.Label(foot, text="", font=font_hint, bg=BG2, fg=MUTED, anchor="w")
    status.pack(side="left", padx=px(20))
    btn_next = flat_button(foot, "开始安装", lambda: None, primary=True, width_chars=12)
    btn_next.pack(side="right", padx=(px(8), px(18)), pady=px(14))
    btn_cancel = flat_button(foot, "取消", root.destroy, width_chars=8)
    btn_cancel.pack(side="right", pady=px(14))

    # ---- 窗口图标 + 深色标题栏
    icon_ok = set_window_icon(root)
    root.update_idletasks()
    dark_ok = dark_titlebar(root)

    ui_queue: list = []

    def pump():
        while ui_queue:
            kind, payload = ui_queue.pop(0)
            if kind == "progress":
                pct, text = payload
                bar["value"] = pct * 100
                now.configure(text=text)
            elif kind == "log":
                logbox.configure(state="normal")
                logbox.insert("end", payload + "\n")
                logbox.see("end")
                logbox.configure(state="disabled")
            elif kind == "done":
                result = payload
                step2.pack_forget()
                step3.pack(fill="both", expand=True)
                if result["ok"]:
                    msg = (f"已安装到：\n{result['target']}\n\n"
                           f"程序文件 {result['files']} 个 · 快捷方式 {len(result['shortcuts'])} 个")
                    if result.get("warnings"):
                        msg += "\n\n注意：" + "；".join(result["warnings"])
                    done_text.configure(text=msg, fg=MUTED)
                    status.configure(text="安装完成", fg=ACCENT)
                    btn_next.configure(text="完成并启动" if v_launch.get() else "完成")
                    btn_next.configure(command=finish)
                else:
                    done_text.configure(text="安装失败：\n" + "\n".join(result["errors"]), fg=RED)
                    status.configure(text="安装失败", fg=RED)
                    btn_next.configure(text="关闭", command=root.destroy)
                btn_next.configure(state="normal")
                btn_cancel.configure(text="关闭")
        root.after(80, pump)

    def post(kind, payload=None):
        ui_queue.append((kind, payload))

    installing = {"busy": False}

    def start_install():
        target = Path(dir_var.get().strip() or str(default_dir()))
        if target.exists() and any(target.iterdir()):
            if not messagebox.askyesno("目录不是空的",
                                       f"{target}\n\n里面已经有文件，同名文件会被覆盖，继续吗？"):
                return
        installing["busy"] = True
        step1.pack_forget()
        step2.pack(fill="both", expand=True)
        btn_next.configure(state="disabled", text="安装中…")
        btn_cancel.configure(text="关闭")
        status.configure(text=f"安装到 {target}")

        def worker():
            result = perform_install(
                target,
                shortcuts=v_desktop.get() or v_menu.get(),
                launch=False,
                log=lambda m: post("log", str(m)),
                progress=lambda p, t: post("progress", (p, t)),
            )
            result["launch"] = v_launch.get()
            post("done", result)

        threading.Thread(target=worker, daemon=True).start()

    def finish():
        target = Path(dir_var.get().strip())
        exe = target / FOLDER / EXE_NAME
        if v_launch.get() and exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
            except Exception:  # noqa: BLE001
                pass
        root.destroy()

    btn_next.configure(command=start_install)

    def on_close():
        if installing["busy"] and not step3.winfo_ismapped():
            if not messagebox.askyesno("正在安装", "安装还没结束，确定要关闭吗？"):
                return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # 自检模式：只把界面建起来、量一下尺寸就退出（不弹给用户）
    if getattr(args, "ui_selftest", None):
        root.geometry(f"+{sw + 600}+{sh + 600}")  # 挪到屏幕外，避免打扰
        root.update_idletasks()
        root.update()
        report = {
            "scale": round(s, 2),
            "screen": [sw, sh],
            "window": [root.winfo_width(), root.winfo_height()],
            "minsize": [root.minsize()[0], root.minsize()[1]],
            "resizable": list(root.resizable()),
            "title": root.title(),
            "icon_set": icon_ok,
            "dark_titlebar": dark_ok,
            "fonts": [font_title[1], font_body[1]],
            "widgets": {
                "header_h": head_h,
                "entry_width": entry.winfo_width(),
                "bar_height": bar.winfo_reqheight(),
            },
        }
        try:
            Path(args.ui_selftest).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        root.destroy()
        return 0

    root.after(80, pump)
    root.mainloop()
    return 0


# ---------------------------------------------------------------- 入口
def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--silent")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--desktop")
    parser.add_argument("--report")
    parser.add_argument("--ui-selftest")
    args, _unknown = parser.parse_known_args()
    if args.silent:
        return silent_main(args)
    try:
        return gui_main(args)
    except Exception:  # noqa: BLE001
        # 没有图形环境时退回静默安装到默认目录
        args.silent = str(default_dir())
        args.no_launch = True
        return silent_main(args)


if __name__ == "__main__":
    sys.exit(main())
