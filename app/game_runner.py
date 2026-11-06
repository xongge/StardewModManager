from __future__ import annotations

"""进程运行器：用 CREATE_NO_WINDOW 启动 SMAPI/原版并捕获输出。"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .core.levels import LevelTracker
from .game_constants import (
    COLORS,
    CREATE_NO_WINDOW,
    DOTNET_NOISE,
    HOST_FAIL_RE,
    SMAPI_EXE,
    SMAPI_VER_RE,
    VANILLA_EXE,
)
from .game_decode import LineDecoder, decode_line, system_codec

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
            try:
                self.stats.emit(self.errors, self.warnings)   # 退出前推一次最终数字
            except Exception:  # noqa: BLE001
                pass
            self.exited.emit(signed)
            self.close_log()

    def _emit(self, ln: str) -> None:
        if getattr(self, "_tracker", None) is None:
            self._tracker = LevelTracker()
        level = self._tracker.level(ln)
        if level in ("error", "warn"):
            if level == "error":
                self.errors += 1
            else:
                self.warnings += 1
            # 统计数字最多每 0.12 秒推一次，避免刷屏时每行都发信号
            now = time.time()
            if now - getattr(self, "_stats_at", 0.0) > 0.12:
                self._stats_at = now
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
                # 每 64 行才真正落盘一次，避免每行都 flush 拖慢输出
                self._log_lines = getattr(self, "_log_lines", 0) + 1
                if self._log_lines % 64 == 0:
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
