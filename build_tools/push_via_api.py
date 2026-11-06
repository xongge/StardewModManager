"""用 GitHub Git Data API 把本地目录推成 main 上的一个提交（绕过 git push 的网络问题）。

用法： set GH_TOKEN=...  然后 python build_tools/push_via_api.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SRC = WS / "GitHub上传版"
REPO = "xongge/StardewModManager"
API = "https://api.github.com"


def api(method: str, url: str, payload=None):
    token = os.environ.get("GH_TOKEN", "")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SDVMM-push")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        print("缺少 GH_TOKEN")
        return 2
    files = sorted(p for p in SRC.rglob("*") if p.is_file() and ".git" not in p.parts)
    print(f"本地文件 {len(files)} 个")

    ref = api("GET", f"{API}/repos/{REPO}/git/ref/heads/main")
    parent_sha = ref["object"]["sha"]
    parent = api("GET", f"{API}/repos/{REPO}/git/commits/{parent_sha}")
    base_tree = parent["tree"]["sha"]
    print("远端父提交:", parent_sha[:8], "| 基线 tree:", base_tree[:8])

    entries = []
    for path in files:
        rel = path.relative_to(SRC).as_posix()
        blob = api("POST", f"{API}/repos/{REPO}/git/blobs", {
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "encoding": "base64",
        })
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    print("已上传 blob:", len(entries))

    tree = api("POST", f"{API}/repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    print("新 tree:", tree["sha"][:8])

    # 远端有、本地没有的文件要删掉（base_tree 里多出来的）
    local_paths = {e["path"] for e in entries}
    remote_paths = {t["path"] for t in api("GET", f"{API}/repos/{REPO}/git/trees/{base_tree}?recursive=1")["tree"]
                    if t["type"] == "blob"}
    removed = sorted(remote_paths - local_paths)
    if removed:
        print("需要删除:", removed[:10], f"（共 {len(removed)}）")
        del_entries = [{"path": p, "mode": "100644", "type": "blob", "sha": None} for p in removed]
        tree = api("POST", f"{API}/repos/{REPO}/git/trees",
                   {"base_tree": tree["sha"], "tree": del_entries})
        print("清理后 tree:", tree["sha"][:8])

    commit = api("POST", f"{API}/repos/{REPO}/git/commits", {
        "message": "release: v1.4.2 (one-click in-app update)",
        "tree": tree["sha"],
        "parents": [parent_sha],
    })
    print("新提交:", commit["sha"][:8])
    api("PATCH", f"{API}/repos/{REPO}/git/refs/heads/main", {"sha": commit["sha"], "force": False})
    print("已更新 main 指向新提交")
    print("COMMIT:", commit["sha"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
