"""配置与数据目录。

优先放在程序自己的目录（安装目录），这样你能直接看到、直接改
`config.json`；如果程序目录不可写（例如装在 Program Files），再退回
`%APPDATA%\\StardewModManager`，并自动迁移旧的配置文件。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import APP_ID

DEFAULTS = {
    # 界面 / 图标（可以直接在 config.json 里改，不用进设置）
    "icon": "icon.ico",          # 支持 .ico/.png，可写绝对路径
    "theme_accent": "",          # 例如 "#4cc38a"，留空用默认
    "animations": True,          # 界面动画开关
    # 目录
    "mods_dir": "",
    "game_dir": "",
    "disabled_dir_name": "Mods.disabled",
    "auto_detect": True,
    "auto_check_smapi": True,
    "extra_args": "",
    "max_console_lines": 6000,
    # AI 汉化（任意 OpenAI 兼容接口）
    "ai_base": "https://token.sensenova.cn/v1",
    "ai_key": "",
    "ai_model": "",
    "ai_models": [],
    "translate_enabled": True,
    "show_original_name": False,
    "write_name_to_manifest": False,   # 汉化名称时同时写入 manifest.json
    "nexus_key": "",                   # Nexus Mods API Key（可选，更稳）
    "nexus_cookie": "",                # Nexus 浏览器 Cookie（免申请，抓公开页面用）
    # 软件自身更新（GitHub Releases）
    "app_repo": "xongge/StardewModManager",
    "auto_check_app_update": True,
    "last_app_check": "",
    "dismissed_version": "",
    # 其它
    "categories": {},
    "last_smapi_check": "",
    "last_smapi_version": "",
}

_APP_DIR: Path | None = None
_DATA_DIR: Path | None = None


def app_dir() -> Path:
    """程序所在目录（打包成 exe 时是 exe 所在目录）。"""
    global _APP_DIR
    if _APP_DIR is None:
        if getattr(sys, "frozen", False):
            _APP_DIR = Path(sys.executable).resolve().parent
        else:
            _APP_DIR = Path(__file__).resolve().parent.parent
    return _APP_DIR


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".dsh_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


def legacy_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_ID


def data_dir() -> Path:
    """配置文件、缓存、日志所在目录。

    打包成 exe 时不从 %APPDATA% 迁移任何东西——否则会把别人的（或自己的）
    密钥、缓存复制进程序目录，一旦转发出去就泄漏了。
    """
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    here = app_dir()
    frozen = bool(getattr(sys, "frozen", False))
    if _writable(here):
        old = legacy_dir()
        if old.is_dir() and not frozen:
            for name in ("config.json", "name_map.json", "label_map.json"):
                src, dst = old / name, here / name
                try:
                    if src.exists() and not dst.exists():
                        shutil.copy2(src, dst)
                except Exception:  # noqa: BLE001
                    pass
        _DATA_DIR = here
    else:
        try:
            old = legacy_dir()
            old.mkdir(parents=True, exist_ok=True)
            _DATA_DIR = old
        except Exception:  # noqa: BLE001
            _DATA_DIR = here
    return _DATA_DIR


def config_path() -> Path:
    return data_dir() / "config.json"


def cache_path(name: str) -> Path:
    return data_dir() / name


def log_dir() -> Path:
    p = data_dir() / "logs"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return p


# 兼容旧调用
def config_dir() -> Path:
    return data_dir()


class Config:
    """配置读写。API Key 一类的敏感字段用 Windows DPAPI 加密后保存，
    明文不会出现在 config.json 里，复制到别的电脑也无法解密。"""

    SECRET_KEYS = ("ai_key", "nexus_key", "nexus_cookie")

    def __init__(self) -> None:
        self.path = config_path()
        self.data: dict = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
        except Exception:  # noqa: BLE001
            pass
        self._migrate_secrets()

    def _migrate_secrets(self) -> None:
        """把以前保存的明文密钥加密后落盘，并从内存/文件里去掉明文。"""
        from . import secrets

        changed = False
        for key in self.SECRET_KEYS:
            plain = str(self.data.get(key) or "").strip()
            if not plain:
                continue
            blob = secrets.protect(plain)
            if blob:
                self.data[f"{key}_dpapi"] = blob
                self.data[key] = ""
                changed = True
        if changed:
            self.save()

    def secret(self, key: str) -> str:
        from . import secrets

        blob = str(self.data.get(f"{key}_dpapi") or "")
        if blob:
            value = secrets.unprotect(blob)
            if value:
                return value
        # 兼容：老配置里的明文
        return str(self.data.get(key) or "")

    def set_secret(self, key: str, value: str) -> None:
        from . import secrets

        value = str(value or "").strip()
        blob = secrets.protect(value) if value else ""
        if blob:
            self.data[f"{key}_dpapi"] = blob
            self.data[key] = ""
        else:
            # 无法加密（非 Windows / 加密失败）才退回明文
            self.data.pop(f"{key}_dpapi", None)
            self.data[key] = value

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.path)
        except Exception:  # noqa: BLE001
            pass

    def ensure_file(self) -> Path:
        """确保配置文件存在（方便用户找到并手改）。"""
        if not self.path.exists():
            self.save()
        return self.path

    def get(self, key, default=None):
        if key in self.SECRET_KEYS:
            return self.secret(key)
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def set(self, key, value) -> None:
        if key in self.SECRET_KEYS:
            self.set_secret(key, value)
            return
        self.data[key] = value

    def update(self, **kw) -> None:
        for k, v in kw.items():
            self.set(k, v)
        self.save()


CONFIG_FILE = config_path
