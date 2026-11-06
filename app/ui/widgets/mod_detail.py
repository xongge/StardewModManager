"""模组详情面板的 HTML 生成（纯展示，便于单独调整样式）。"""
from __future__ import annotations

from pathlib import Path

from ..theme import C


def esc(text) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mod_html(mod, ctx, update_info: dict | None = None) -> str:
    """生成详情面板 HTML。ctx 提供 translated_name / name_source。"""
    sev = {"error": C["red"], "warn": C["yellow"], "info": C["muted"]}
    probs = "".join(
        f'<div style="color:{sev[p.severity]};">● {esc(p.text)}</div>' for p in mod.problems
    ) or f'<div style="color:{C["accent"]};">● 未发现问题</div>'
    state = (
        f'<span style="color:{C["accent"]};">已启用</span>'
        if mod.enabled
        else f'<span style="color:{C["muted"]};">已停用</span>'
    )
    links = ""
    for key in mod.update_keys:
        if key.lower().startswith("nexus:"):
            mod_id = esc(key.split(":", 1)[1])
            links += (
                f'<a style="color:{C["blue"]};" '
                f'href="https://www.nexusmods.com/stardewvalley/mods/{mod_id}">Nexus</a> '
            )
    cp_line = ""
    if mod.content_pack_for:
        cp_line = f'<div style="color:{C["muted"]};">内容包框架：{esc(mod.content_pack_for)}</div>'
    zh = ctx.translated_name(mod)
    src = ctx.name_source(mod)
    zh_line = (
        f'<div style="color:{C["accent"]};font-weight:700;">{esc(zh)}'
        f'<span style="color:{C["muted"]};font-weight:400;font-size:12px;">　（{esc(src)}）</span></div>'
        if zh and zh != mod.name
        else ""
    )
    cfg_path = Path(mod.folder) / "config.json"
    cfg_line = (
        f'<div style="color:{C["accent"]};">● 已有配置文件 config.json，可以点下面「编辑配置」图形化修改</div>'
        if cfg_path.exists()
        else f'<div style="color:{C["muted"]};">● 还没有 config.json（进一次游戏后一般会生成）</div>'
    )
    info = update_info or {}
    up_line = ""
    if info.get("status") == "new":
        up_line = (
            f'<div style="color:{C["accent"]};font-weight:700;">⬆ 有新版本：'
            f'{esc(mod.display_version)} → {esc(info.get("latest"))}'
            f'　<a style="color:{C["blue"]};" href="{esc(info.get("url") or "#")}">前往下载</a></div>'
        )
    elif info:
        note = info.get("note") or {
            "ok": "已是最新版本", "skip": "无法自动检查", "error": "查询失败",
        }.get(info.get("status"), "")
        up_line = f'<div style="color:{C["muted"]};">● 更新检查：{esc(note)}</div>'
    return f"""
        {zh_line}
        <div style="font-size:15px;font-weight:700;">{esc(mod.name)}</div>
        <div style="color:{C['muted']};">{esc(mod.author or '未知作者')} · v{esc(mod.display_version)} · {esc(mod.kind)} · {state}</div>
        <hr style="border:none;border-top:1px solid {C['line']};">
        <div style="color:{C['muted']};">UniqueID：{esc(mod.unique_id or '-')}　最低 SMAPI：{esc(mod.min_api or '-')}</div>
        <div style="color:{C['muted']};">文件夹：{esc(mod.folder_name)}</div>
        <div style="color:{C['muted']};">路径：{esc(mod.folder)}</div>
        {cp_line}
        <div style="margin:6px 0;">{esc(mod.description)}</div>
        <div style="margin-top:8px;">{probs}</div>
        <div style="margin-top:6px;">{cfg_line}</div>
        <div style="margin-top:6px;">{up_line}</div>
        <div style="margin-top:6px;">{links}</div>
        """


def mod_html_for(page, mod) -> str:
    """页面内调用的小包装：带上页面缓存的更新信息。"""
    return mod_html(mod, page.ctx, page._update_of(mod))
