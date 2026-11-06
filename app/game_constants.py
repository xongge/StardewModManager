from __future__ import annotations

"""游戏相关的常量（路径名、正则、颜色、需要清理的环境变量）。"""
import re

CREATE_NO_WINDOW = 0x08000000
SMAPI_EXE = "StardewModdingAPI.exe"
VANILLA_EXE = "Stardew Valley.exe"

SMAPI_VER_RE = re.compile(r"SMAPI\s+(\d+\.\d+\.\d+)")
HOST_FAIL_RE = re.compile(
    r"hostpolicy\.dll|hostfxr|Failed to run as a self-contained app|did not specify a framework",
    re.I,
)

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

COLORS = {
    "error": ("#ff8a80", "#2a1414"),
    "warn": ("#ffd166", "#2a2410"),
    "trace": ("#7f8c9b", None),
    "info": ("#d6deeb", None),
    "sys": ("#7ee787", None),
}
