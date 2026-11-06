"""游戏目录探测 + 进程运行 + 输出解码（门面：保持原有 from .game import X 可用）。

实现拆分到：
- game_constants.py  常量与颜色
- game_decode.py     输出解码
- game_detect.py     目录探测
- game_runner.py     进程运行器
"""
from __future__ import annotations

from .core.levels import (  # noqa: F401
    CONTEXT_BLOCK,
    ERROR_HINTS,
    LEVEL_RE,
    WARN_HINTS,
    LevelTracker,
    classify,
)
from .game_constants import (  # noqa: F401
    COLORS,
    CREATE_NO_WINDOW,
    DOTNET_NOISE,
    HOST_FAIL_RE,
    SMAPI_EXE,
    SMAPI_VER_RE,
    VANILLA_EXE,
)
from .game_decode import LineDecoder, decode_line, system_codec  # noqa: F401
from .game_detect import (  # noqa: F401
    _FALLBACK_DIRS,
    _library_paths,
    _score_game_dir,
    _steam_roots,
    _valid_game_dir,
    default_mods_dir,
    detect_game_dir,
    find_smapi_only_dirs,
    find_vanilla_exe,
    iter_game_candidates,
    validate_game_dir,
)
from .game_runner import GameRunner  # noqa: F401

__all__ = [
    "GameRunner",
    "COLORS",
    "CREATE_NO_WINDOW",
    "DOTNET_NOISE",
    "HOST_FAIL_RE",
    "SMAPI_EXE",
    "SMAPI_VER_RE",
    "VANILLA_EXE",
    "LineDecoder",
    "decode_line",
    "system_codec",
    "LevelTracker",
    "classify",
    "default_mods_dir",
    "detect_game_dir",
    "find_smapi_only_dirs",
    "find_vanilla_exe",
    "iter_game_candidates",
    "validate_game_dir",
]
