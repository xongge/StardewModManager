"""游戏目录探测 + 进程启动/停止 + 日志分级解析（把 CMD 窗口集成进应用）。"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

CREATE_NO_WINDOW = 0x08000000
SMAPI_EXE = "StardewModdingAPI.exe"
VANILLA_EXE = "Stardew Valley.exe"

def _steam_library_dirs() -> list:
    """从注册表读所有 Steam 库目录（不写死任何人的盘符）。"""
    dirs = []
    try:
        import winreg

        keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        steam_roots = []
        for root, path, name in keys:
            try:
                with winreg.OpenKey(root, path) as key:
                    value = str(winreg.QueryValueEx(key, name)[0])
                    if value:
                        steam_roots.append(Path(value.replace("/", "\\")))
            except OSError:
                continue
        for lib in steam_roots:
            dirs.append(lib / "steamapps" / "common" / "Stardew Valley")
            vdf = lib / "steamapps" / "libraryfolders.vdf"
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(m.group(1).replace("\\\\", "\\"))
                    dirs.append(p / "steamapps" / "common" / "Stardew Valley")
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return dirs


def _fallback_dirs() -> list:
    """常见安装位置：各盘符 + Steam 注册表 + GOG 默认目录。"""
    dirs = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley"),
        Path(r"C:\Program Files\Steam\steamapps\common\Stardew Valley"),
        Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Stardew Valley"),
        Path(r"C:\GOG Games\Stardew Valley"),
    ]
    for letter in "CDEFGHIJ":
        dirs.append(Path(f"{letter}:\\Steam\\steamapps\\common\\Stardew Valley"))
        dirs.append(Path(f"{letter}:\\SteamLibrary\\steamapps\\common\\Stardew Valley"))
        dirs.append(Path(f"{letter}:\\Games\\Stardew Valley"))
    dirs.extend(_steam_library_dirs())
    out, seen = [], set()
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


_FALLBACK_DIRS = _fallback_dirs()

LEVEL_RE = re.compile(r"\b(ERROR|ALERT|CRITICAL|FATAL|WARN|WARNING|TRACE|DEBUG)\b")
SMAPI_VER_RE = re.compile(r"SMAPI\s+(\d+\.\d+\.\d+)")
HOST_FAIL_RE = re.compile(r"hostpolicy\.dll|hostfxr|Failed to run as a self-contained app|did not specify a framework", re.I)

# SMAPI 的控制台输出没有 ERROR/WARN 前缀（那是它日志文件的格式，红色是它自己上色的），
# 所以这里按内容 + 上下文判断级别，才能在应用内像 CMD 那样标红。
ERROR_HINTS = (
    "error", "failed", "failure", "exception", "crash", "could not", "cannot ", "can't ",
    "unable to", "not found", "missing", "invalid", "conflict", "denied", "aborted",
    "fatal", "no longer", "incompatible", "unexpected", "not loaded",
)
WARN_HINTS = (
    "warn", "deprecat", "ignored", "skipped", "unsupported", "outdated", "out-of-date",
    "requires smapi", "not compatible", "may not work", "recommend", "but you have",
    "not compatible", "out of date",
)
CONTEXT_BLOCK = (
    "could not be added", "skipped mods", "these mods", "no longer compatible",
    "consider updating", "error log",
)


class LevelTracker:
    """按内容 + 上下文判断一行属于 error / warn / info（有状态）。"""

    def __init__(self) -> None:
        self.context = ""
        self.remain = 0

    def level(self, line: str) -> str:
        text = line or ""
        low = text.lower()
        m = LEVEL_RE.search(text)
        if m:
            lv = m.group(1)
            if lv in ("ERROR", "ALERT", "CRITICAL", "FATAL"):
                return "error"
            if lv in ("WARN", "WARNING"):
                return "warn"
            if lv in ("TRACE", "DEBUG"):
                return "trace"
            return "info"
        stripped = text.strip()
        indented = (
            text.startswith((" ", "\t"))
            or stripped.startswith(("-", "•"))
            or bool(re.match(r"^\[[^\]]+\]\s+[-•]", text))   # [SMAPI]   - 条目
            or "   " in text[:24]
        )
        if not indented:
            # 新区块开始：清掉上一段上下文，免得把后面的行也染成红色
            self.context = ""
            self.remain = 0
        for key in CONTEXT_BLOCK:
            if key in low:
                self.context = "warn" if key in ("skipped mods", "consider updating") else "error"
                self.remain = 60
                break
        if self.remain > 0 and indented:
            self.remain -= 1
            if self.context:
                return self.context
        if any(h in low for h in ERROR_HINTS):
            return "error"
        if any(h in low for h in WARN_HINTS):
            return "warn"
        return "info"


def classify(line: str) -> str:
    """无状态快速判断（控制台以外的地方用）。"""
    return LevelTracker().level(line)

# 这些环境变量会干扰自包含 .NET 应用的宿主解析（hostpolicy.dll 报错的常见原因）
DOTNET_NOISE = (
    "DOTNET_STARTUP_HOOKS",
    "DOTNET_SHARED_STORE",
    "DOTNET_ADDITIONAL_DEPS",
    "DOTNET_HOST_PATH",
    "DOTNET_MSBUILD_SDK_RESOLVER_CLI_DIR",
    "COREHOST_TRACE",
    "COREHOST_TRACEFILE",
    "COREHOST_TRACE_VERBOSITY",
)


def system_codec() -> str:
    """当前系统的 ANSI 代码页名（中文 Windows 上是 cp936）。"""
    try:
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetACP()}"
    except Exception:  # noqa: BLE001
        return "mbcs"


def decode_line(raw: bytes, prefer: str | None = None) -> tuple:
    """智能解码一行输出：优先 UTF-8，失败则用系统 ANSI 代码页。返回 (文本, 使用的编码)。"""
    for codec in ([prefer] if prefer else []) + ["utf-8", system_codec(), "gbk", "cp1252"]:
        if not codec:
            continue
        try:
            return raw.decode(codec), codec
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


class LineDecoder:
    """把子进程的原始字节切成文本行。

    SMAPI（.NET 控制台程序）在输出被重定向时会写 **UTF-16LE**，
    直接按 UTF-8 解会得到 “S M A P I” 这种夹着 \\x00 的乱码（显示成方框、复制出来也是乱的）。
    这里自动识别 UTF-16LE / UTF-16BE（含 BOM）与本地代码页（中文 Windows 的 GBK）。
    """

    def __init__(self) -> None:
        self.codec: str | None = None   # None=未判定；'utf-16-le'/'utf-16-be'/'text'
        self.buf = bytearray()
        self.text = ""

    # ---------------- 编码判定
    def _detect(self, force: bool = False) -> None:
        data = bytes(self.buf)
        if len(data) >= 2:
            if data[:2] == b"\xff\xfe":
                self.codec = "utf-16-le"
                del self.buf[:2]
                return
            if data[:2] == b"\xfe\xff":
                self.codec = "utf-16-be"
                del self.buf[:2]
                return
        if not data:
            return
        if len(data) < 4 and not force:
            return
        sample = data[:256]
        nuls = sample.count(0)
        if nuls and nuls >= max(1, len(sample) // 4):
            even = sum(1 for i in range(0, len(sample) - 1, 2) if sample[i] == 0)
            odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
            self.codec = "utf-16-be" if even > odd else "utf-16-le"
            return
        self.codec = "text"

    # ---------------- 输入
    def feed(self, data: bytes) -> list:
        self.buf += data
        if self.codec is None:
            self._detect()
            if self.codec is None:
                return []
        if self.codec in ("utf-16-le", "utf-16-be"):
            usable = len(self.buf) - (len(self.buf) % 2)
            if usable <= 0:
                return []
            self.text += bytes(self.buf[:usable]).decode(self.codec, "replace")
            del self.buf[:usable]
        else:
            while True:
                idx = self.buf.find(b"\n")
                if idx < 0:
                    break
                raw = bytes(self.buf[:idx])
                del self.buf[: idx + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                line, _ = decode_line(raw)
                self.text += line + "\n"
        return self._pop_lines()

    def flush(self) -> list:
        self._detect(force=True)
        if self.buf:
            if self.codec in ("utf-16-le", "utf-16-be"):
                self.text += bytes(self.buf).decode(self.codec, "replace")
            else:
                line, _ = decode_line(bytes(self.buf))
                self.text += line
            self.buf.clear()
        out = self._pop_lines()
        if self.text:
            out.append(self.text.rstrip("\r"))
            self.text = ""
        return out

    def _pop_lines(self) -> list:
        out = []
        while "\n" in self.text:
            line, self.text = self.text.split("\n", 1)
            out.append(line.rstrip("\r"))
        return out



def classify(line: str) -> str:
    m = LEVEL_RE.search(line or "")
    if m:
        lv = m.group(1)
        if lv in ("ERROR", "ALERT", "CRITICAL", "FATAL"):
            return "error"
        if lv in ("WARN", "WARNING"):
            return "warn"
        if lv in ("TRACE", "DEBUG"):
            return "trace"
    return "info"


# ---------------------------------------------------------------- 目录探测
def _steam_roots():
    roots = []
    try:
        import winreg
    except Exception:  # noqa: BLE001
        return roots
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as k:
                for value in ("SteamPath", "InstallPath"):
                    try:
                        v, _ = winreg.QueryValueEx(k, value)
                        if v:
                            roots.append(Path(v))
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def _library_paths(steam_root: Path):
    out = []
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                out.append(Path(m.group(1).replace("\\\\", "\\")))
        except Exception:  # noqa: BLE001
            pass
    out.append(steam_root)
    return out


def _valid_game_dir(p: Path) -> bool:
    """只有含游戏本体的目录才算游戏目录（只有 SMAPI 残留的目录不算）。"""
    try:
        return (p / VANILLA_EXE).exists()
    except OSError:
        return False


def _score_game_dir(p: Path) -> int:
    score = 0
    if (p / VANILLA_EXE).exists():
        score += 8
    if (p / "Stardew Valley.dll").exists():
        score += 4
    if (p / "Content").is_dir():
        score += 2
    if (p / SMAPI_EXE).exists():
        score += 1
    if (p / "Mods").is_dir():
        score += 1
    return score


def iter_game_candidates() -> list:
    """所有可能的星露谷目录（Steam 各库 + 常见路径），去掉重复。"""
    out = []
    seen = set()

    def add(path):
        try:
            p = Path(path)
        except Exception:  # noqa: BLE001
            return
        key = str(p).lower().rstrip("\\/")
        if key and key not in seen:
            seen.add(key)
            out.append(p)

    for root in _steam_roots():
        for lib in _library_paths(root):
            add(Path(str(lib)) / "steamapps" / "common" / "Stardew Valley")
    for raw in _FALLBACK_DIRS:
        add(raw)
    return out


def detect_game_dir() -> str:
    """挑出真正的游戏目录（优先含 Stardew Valley.exe，其次内容最完整的）。"""
    best, best_score = "", 0
    for p in iter_game_candidates():
        if not p.is_dir():
            continue
        score = _score_game_dir(p)
        if score > best_score:
            best, best_score = str(p), score
    # 至少要能看到游戏本体，否则不算找到
    return best if best_score >= 8 else ""


def find_smapi_only_dirs() -> list:
    """只有 SMAPI 没有游戏本体的目录（常见于换盘后留下的残留）。"""
    out = []
    for p in iter_game_candidates():
        if p.is_dir() and not (p / VANILLA_EXE).exists() and (p / SMAPI_EXE).exists():
            out.append(str(p))
    return out


def validate_game_dir(game_dir: str) -> dict:
    gd = Path(game_dir) if game_dir else None
    info = {"path": str(gd or ""), "exists": False, "has_game": False, "has_smapi": False, "reason": ""}
    if not gd or not gd.is_dir():
        info["reason"] = "目录不存在"
        return info
    info["exists"] = True
    info["has_game"] = (gd / VANILLA_EXE).exists()
    info["has_smapi"] = (gd / SMAPI_EXE).exists()
    if not info["has_game"]:
        info["reason"] = "这个目录里没有游戏本体 Stardew Valley.exe（只有 SMAPI 的残留文件）"
    return info


def default_mods_dir(game_dir: str) -> str:
    return str(Path(game_dir) / "Mods") if game_dir else ""


VANILLA_BACKUP_SUFFIXES = (".wjdl.backup", ".bak", ".orig", ".original", ".vanilla", ".backup")


def find_vanilla_exe(game_dir: str) -> tuple:
    """找“真正的原版启动文件”。

    有些第三方工具（例如带 .wjdl.backup 的那种）会把 Stardew Valley.exe 换成
    加载 SMAPI 的启动器，这时点「原版启动」其实还是会带 Mod。这里优先使用备份文件。
    返回 (路径, 说明文字)。
    """
    gd = Path(game_dir) if game_dir else None
    if not gd:
        return "", ""
    main = gd / VANILLA_EXE
    for suffix in VANILLA_BACKUP_SUFFIXES:
        cand = gd / (VANILLA_EXE + suffix)
        if cand.exists():
            return str(cand), f"{VANILLA_EXE} 已被第三方工具替换，原版启动改用备份：{cand.name}"
    return str(main), ""


# ---------------------------------------------------------------- 运行器
COLORS = {
    "error": ("#ff8a80", "#2a1414"),
    "warn": ("#ffd166", "#2a2410"),
    "trace": ("#7f8c9b", None),
    "info": ("#d6deeb", None),
    "sys": ("#7ee787", None),
}


class GameRunner(QObject):
    """用 subprocess + CREATE_NO_WINDOW 捕获 stdout/stderr。

    这样 SMAPI 的输出会进入应用内控制台，Windows 不会再弹出 CMD 黑窗。
    """

    line = Signal(str, str, str)      # raw, level, html
    stats = Signal(int, int)          # errors, warnings
    state = Signal(str)               # running / stopped / starting
    smapiVersion = Signal(str)
    exited = Signal(object)
    hint = Signal(str)                # 需要提示用户的诊断结论

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._buf = ""
        self._thread: threading.Thread | None = None
        self._finished = False
        self._selfcontained = False
        self.host_failed = False
        self.errors = 0
        self.warnings = 0
        self.log_file = None
        self._label = ""

    # ---------------- 状态
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def pid(self) -> int:
        return self._proc.pid if self._proc else 0

    # ---------------- 启动
    def start(self, program: str, args=None, cwd: str = "", label: str = "", env_extra=None) -> bool:
        if self.running:
            return False
        if not program or not Path(program).exists():
            self.emit_system(f"[管理器] 找不到可执行文件：{program or '(空)'}，请在设置里检查游戏目录。")
            return False
        if program.lower().endswith(".bat"):
            argv = ["cmd", "/c", program] + list(args or [])
        else:
            argv = [program] + list(args or [])
        self.errors = 0
        self.warnings = 0
        self._buf = ""
        self._finished = False
        self.host_failed = False
        self._tracker = LevelTracker()
        self._label = label or Path(program).name
        self.stats.emit(0, 0)
        self.reset_log()
        self.state.emit("starting")
        self.emit_system(f"[管理器] 正在启动：{' '.join(argv)}".strip())

        env = dict(os.environ)
        # 清理会干扰自包含 .NET 宿主的环境变量
        for key in DOTNET_NOISE:
            env.pop(key, None)
        gd = Path(cwd) if cwd else None
        if gd and (gd / "hostpolicy.dll").exists():
            # 游戏目录自带运行时，此时 DOTNET_ROOT 会让宿主去错误的位置找 hostpolicy.dll
            self._selfcontained = True
            for key in ("DOTNET_ROOT", "DOTNET_ROOT_X64", "DOTNET_ROOT_X86", "DOTNET_ROOT(x86)"):
                env.pop(key, None)
        else:
            self._selfcontained = False
        env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        env["DOTNET_NOLOGO"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        for k, v in (env_extra or {}).items():
            env[str(k)] = str(v)

        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(  # noqa: S603
                argv,
                cwd=cwd or None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            self._proc = None
            self.emit_system(f"[管理器] 进程启动失败：{exc}")
            self.state.emit("stopped")
            self.close_log()
            return False

        self.state.emit("running")
        self._thread = threading.Thread(target=self._reader, name="console-reader", daemon=True)
        self._thread.start()
        return True

    def write_input(self, text: str) -> bool:
        proc = self._proc
        if not self.running or proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write((text + "\r\n").encode("utf-8", "ignore"))
            proc.stdin.flush()
            return True
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 停止
    def stop(self) -> bool:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        self.emit_system("[管理器] 正在停止游戏进程（含子进程）…")
        if sys.platform == "win32" and proc.pid:
            try:
                subprocess.run(  # noqa: S603
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20,
                )
                return True
            except Exception:  # noqa: BLE001
                pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            return False
        return True

    # ---------------- 输出读取线程
    def _reader(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        decoder = LineDecoder()
        try:
            while True:
                chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
                if not chunk:
                    break
                for line in decoder.feed(chunk):
                    self._emit(line)
        except Exception:  # noqa: BLE001
            pass
        try:
            for line in decoder.flush():
                self._emit(line)
        except Exception:  # noqa: BLE001
            pass
        self._buf = ""
        try:
            proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            pass
        code = proc.returncode if proc.returncode is not None else -1
        if not self._finished:
            self._finished = True
            self.state.emit("stopped")
            signed = code
            if signed is not None and signed > 2**31 - 1:
                signed -= 2**32  # 0xC0000005 之类按有符号显示
            text = (
                f"[管理器] {self._label} 已退出（退出码 {signed}"
                + (f" / 0x{code & 0xFFFFFFFF:08X}" if code and code > 2**31 - 1 else "")
                + f"），共 {self.errors} 个错误 / {self.warnings} 个警告。"
            )
            if code not in (0, None):
                self._emit(text)
            else:
                self.emit_system(text)
            self.exited.emit(signed)
            self.close_log()

    def _emit(self, ln: str) -> None:
        if getattr(self, "_tracker", None) is None:
            self._tracker = LevelTracker()
        level = self._tracker.level(ln)
        if level == "error":
            self.errors += 1
            self.stats.emit(self.errors, self.warnings)
        elif level == "warn":
            self.warnings += 1
            self.stats.emit(self.errors, self.warnings)
        m = SMAPI_VER_RE.search(ln)
        if m:
            self.smapiVersion.emit(m.group(1))
        if HOST_FAIL_RE.search(ln) and not self.host_failed:
            self.host_failed = True
            self.hint.emit("smapi-host")
        color, bg = COLORS.get(level, COLORS["info"])
        esc = (
            ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        style = f"color:{color};"
        if level in ("error", "warn"):
            style += "font-weight:700;"          # 加粗，等于给文字描了一圈
        if bg and level in ("error", "warn"):
            style += f"background-color:{bg};"
        self.line.emit(ln, level, f'<span style="{style}">{esc}</span>')
        self.write_log(ln)

    def emit_system(self, text: str) -> None:
        color, _ = COLORS["sys"]
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.line.emit(text, "sys", f'<span style="color:{color};">{esc}</span>')
        self.write_log(text)

    # ---------------- 日志落盘
    def reset_log(self) -> None:
        self.close_log()
        try:
            from .config import log_dir
            import datetime

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file = open(log_dir() / f"console_{stamp}.log", "w", encoding="utf-8")  # noqa: SIM115
        except Exception:  # noqa: BLE001
            self.log_file = None

    def write_log(self, text: str) -> None:
        if self.log_file:
            try:
                self.log_file.write(text + "\n")
                self.log_file.flush()
            except Exception:  # noqa: BLE001
                pass

    def close_log(self) -> None:
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:  # noqa: BLE001
                pass
            self.log_file = None

    def wait(self, timeout: float = 5.0) -> None:
        """等待输出读取线程结束（退出时保证日志写完）。"""
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout)
        self.close_log()
