"""全局上下文：配置、Mod 仓库、运行器、SMAPI 状态。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import mods as modlib
from .ai import NameCache
from .config import Config, config_dir
from .game import (
    GameRunner,
    default_mods_dir,
    detect_game_dir,
    find_smapi_only_dirs,
    validate_game_dir,
)


class ScanWorker(QThread):
    done = Signal(object)

    def __init__(self, mods_dir, disabled_dir, smapi_version, parent=None):
        super().__init__(parent)
        self._m = mods_dir
        self._d = disabled_dir
        self._v = smapi_version

    def run(self) -> None:  # noqa: D102
        try:
            result = modlib.scan(self._m, self._d, self._v)
            # 顺便读取各 Mod 自带 i18n/zh.json 里的中文名
            from . import modconfig

            for mod in result:
                try:
                    mod.zh_name = modconfig.localized_mod_name(mod.folder)
                except Exception:  # noqa: BLE001
                    mod.zh_name = ""
        except Exception as exc:  # noqa: BLE001
            result = []
            self._err = str(exc)
        self.done.emit(result)


class AppContext(QObject):
    modsChanged = Signal()
    status = Signal(str)
    smapiInfoChanged = Signal()
    logLine = Signal(str)

    def log(self, text: str) -> None:
        self.logLine.emit(text)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.config = Config()
        self.runner = GameRunner(self)
        self.mods: list = []
        self.scanning = False
        self.smapi_installed = ""
        self.smapi_latest: dict | None = None
        self.names = NameCache(config_dir() / "name_map.json")
        self.labels = NameCache(config_dir() / "label_map.json")
        self._worker: ScanWorker | None = None
        if self.config.get("auto_detect"):
            self.auto_detect(silent=True)

    # ---------------- 显示名（优先 Mod 自带汉化，其次 AI/手动缓存）
    def display_name(self, mod) -> str:
        if not self.config.get("translate_enabled", True):
            return mod.name
        return self.translated_name(mod) or mod.name

    def translated_name(self, mod) -> str:
        if getattr(mod, "zh_name", ""):
            return mod.zh_name
        if mod.unique_id:
            return self.names.get(mod.unique_id, mod.name)
        return ""

    def name_source(self, mod) -> str:
        if getattr(mod, "zh_name", ""):
            return "Mod 自带 i18n"
        if mod.unique_id and self.names.get(mod.unique_id, mod.name):
            return "AI / 手动"
        return ""

    # ---------------- 路径
    @property
    def game_dir(self) -> str:
        return str(self.config.get("game_dir") or "")

    @property
    def mods_dir(self) -> Path | None:
        p = str(self.config.get("mods_dir") or "")
        return Path(p) if p else None

    @property
    def disabled_dir_name(self) -> str:
        return str(self.config.get("disabled_dir_name") or "Mods.disabled")

    @property
    def disabled_dir(self) -> Path | None:
        md = self.mods_dir
        return (md.parent / self.disabled_dir_name) if md else None

    @property
    def smapi_exe(self) -> str:
        if not self.game_dir:
            return ""
        return str(Path(self.game_dir) / "StardewModdingAPI.exe")

    def auto_detect(self, silent: bool = False) -> bool:
        changed = False
        if not self.game_dir:
            gd = detect_game_dir()
            if gd:
                self.config.set("game_dir", gd)
                changed = True
        if not self.config.get("mods_dir") and self.config.get("game_dir"):
            self.config.set("mods_dir", default_mods_dir(self.game_dir))
            changed = True
        if changed:
            self.config.save()
        if not silent:
            self.status.emit("已自动检测游戏目录" if changed else "未能自动检测到游戏目录，请手动设置")
        return changed

    # ---------------- 游戏目录校验 / 自动纠正
    def game_dir_problem(self) -> str:
        """返回当前游戏目录的问题描述（没有问题返回空串）。"""
        gd = self.game_dir
        if not gd:
            return ""
        info = validate_game_dir(gd)
        if not info["exists"]:
            return f"游戏目录不存在：{gd}"
        if not info["has_game"]:
            other = detect_game_dir()
            hint = f"\n检测到正确的游戏目录可能是：{other}" if other else ""
            return f"{gd} 里没有游戏本体 Stardew Valley.exe（只有 SMAPI 残留文件）。{hint}"
        return ""

    def fix_game_dir_if_needed(self) -> str:
        """当前游戏目录不对时，自动切换到真正的游戏目录。返回提示信息（无问题返回空串）。"""
        problem = self.game_dir_problem()
        if not problem:
            return ""
        better = detect_game_dir()
        if not better or better == self.game_dir:
            leftovers = find_smapi_only_dirs()
            extra = f"（发现残留目录：{'、'.join(leftovers)}）" if leftovers else ""
            return problem + extra
        old = self.game_dir
        self.config.set("game_dir", better)
        if not self.config.get("mods_dir") or str(self.config.get("mods_dir")).lower().startswith(old.lower()):
            self.config.set("mods_dir", default_mods_dir(better))
        self.config.save()
        self.update_smapi_installed()
        return f"原来的游戏目录（{old}）里没有游戏本体，已自动切换到：{better}"

    # ---------------- 扫描
    def refresh_mods(self) -> None:
        if self.scanning:
            return
        md = self.mods_dir
        if md is None or not md.exists():
            self.mods = []
            self.modsChanged.emit()
            return
        self.scanning = True
        self.status.emit("正在扫描 Mod…")
        worker = ScanWorker(md, self.disabled_dir, self.smapi_installed, self)
        worker.done.connect(self._on_scan_done)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_worker_finished(self) -> None:
        # 线程结束后释放引用，避免访问已被 Qt 删除的 C++ 对象
        self._worker = None

    def _on_scan_done(self, result) -> None:
        self.mods = list(result or [])
        self.scanning = False
        stats = self.stats()
        self.status.emit(
            f"共 {stats['total']} 个 Mod · 启用 {stats['enabled']} · 停用 {stats['disabled']}"
            f" · 错误 {stats['errors']} · 警告 {stats['warnings']}"
        )
        self.modsChanged.emit()

    def stats(self) -> dict:
        return {
            "total": len(self.mods),
            "enabled": sum(1 for m in self.mods if m.enabled),
            "disabled": sum(1 for m in self.mods if not m.enabled),
            "errors": sum(1 for m in self.mods if m.has_error),
            "warnings": sum(1 for m in self.mods if m.has_warn),
        }

    def update_smapi_installed(self) -> str:
        from .smapi import installed_version

        v = installed_version(self.game_dir)
        if v and v != self.smapi_installed:
            self.smapi_installed = v
            self.config.set("last_smapi_version", v)
            self.config.save()
            self.smapiInfoChanged.emit()
        return self.smapi_installed

    def shutdown(self) -> None:
        """退出前收尾：等待扫描线程与输出线程，落盘配置。"""
        worker = self._worker
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(6000)
            except RuntimeError:
                pass
        self.runner.wait(3.0)
        self.config.save()
