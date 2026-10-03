"""星露谷物语 Mod 管理器 —— 启动入口。

运行： python main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    try:
        from app.ui.main_window import run
    except ImportError as exc:  # 缺少依赖时给出中文提示
        print("缺少依赖，请先执行： pip install -r requirements.txt")
        print(f"详细信息：{exc}")
        try:
            import tkinter.messagebox as mb

            mb.showerror(
                "缺少依赖",
                "缺少 PySide6，请先在命令行执行：\n\npip install -r requirements.txt",
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
