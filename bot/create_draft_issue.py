"""drafts/YYYY-MM-DD.json から承認用の Issue を作る（gh CLI を使用）。

使い方:  python bot/create_draft_issue.py drafts/2026-10-20.json
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue_format import LABEL, Draft, render  # noqa: E402
from post_scheduled import validate  # noqa: E402

SLOTS = {"07:00", "12:00", "21:00"}


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


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

    existing = json.loads(gh("issue", "list", "--label", LABEL, "--state", "open", "--json", "number,body"))
    if any(f"date={date_str}" in (i.get("body") or "") for i in existing):
        print(f"{date_str} の投稿案はすでにあります。重複して作りません。")
        return 0

    gh("label", "create", LABEL, "--color", "F9A825", "--description", "承認待ちの投稿案", "--force")
    title, body = render(date_str, posts)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
    url = gh("issue", "create", "--title", title, "--label", LABEL, "--body-file", f.name).strip()
    print(f"投稿案を作成しました：{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
