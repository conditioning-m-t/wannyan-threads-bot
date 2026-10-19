"""drafts/YYYY-MM-DD.json から承認用の Issue を作る（gh CLI を使用）。

使い方:  python bot/create_draft_issue.py drafts/2026-10-20.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue_format import LABEL, Draft, render  # noqa: E402
from post_scheduled import validate  # noqa: E402

SLOTS = {"07:00", "12:00", "21:00"}


def repo_slug() -> str:
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], check=True, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent,
    ).stdout.strip()
    slug = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
    return "/".join(slug.split("/")[-2:])


def gh_api(path: str, method: str = "GET", payload: dict | None = None, ok_codes=()) -> object:
    """gh api（REST）を呼ぶ。Claude Code の環境では GraphQL が使えないため REST のみ使う。"""
    cmd = ["gh", "api", "-X", method, f"repos/{repo_slug()}/{path}"]
    stdin = None
    if payload is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(payload)
    res = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if res.returncode != 0:
        if any(str(c) in res.stdout + res.stderr for c in ok_codes):
            return None
        raise RuntimeError(f"gh api {method} {path} に失敗：{res.stderr.strip() or res.stdout.strip()}")
    return json.loads(res.stdout) if res.stdout.strip() else None


def main(path: str) -> int:
    data = json.loads(Path(path).read_text())
    date_str, posts = data["date"], data["posts"]

    problems = []
    for p in posts:
        if p["slot"] not in SLOTS:
            problems.append(f"{p['slot']}：投稿時刻は 07:00 / 12:00 / 21:00 のどれかにしてください")
        for e in validate(Draft(slot=p["slot"], text=p["text"], reply=p.get("reply"))):
            problems.append(f"{p['slot']}：{e}")
    if len({p["slot"] for p in posts}) != len(posts):
        problems.append("同じ時刻の案が重複しています")
    if problems:
        print("投稿案に問題があるため Issue を作りませんでした：")
        print("\n".join(f"- {x}" for x in problems))
        return 1

    existing = gh_api(f"issues?state=open&labels={quote(LABEL)}&per_page=50") or []
    if any(f"date={date_str}" in (i.get("body") or "") for i in existing):
        print(f"{date_str} の投稿案はすでにあります。重複して作りません。")
        return 0

    gh_api(
        "labels",
        "POST",
        {"name": LABEL, "color": "F9A825", "description": "承認待ちの投稿案"},
        ok_codes=(422, "already_exists"),
    )
    title, body = render(date_str, posts)
    issue = gh_api("issues", "POST", {"title": title, "body": body, "labels": [LABEL]})
    print(f"投稿案を作成しました：{issue['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
