"""drafts/YYYY-MM-DD.json から承認用の Issue を作る。

使い方:  python bot/create_draft_issue.py drafts/2026-10-20.json
         ACCOUNT=<アカウント名> python bot/create_draft_issue.py accounts/<アカウント名>/drafts/2026-10-20.json
（ACCOUNT を省くとペットのアカウント）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account  # noqa: E402
from gh_cli import find_issue, gh_api  # noqa: E402
from issue_format import LABEL, Draft, render  # noqa: E402
from post_scheduled import validate  # noqa: E402

ACCOUNT = account.load()


def check(posts: list[dict]) -> list[str]:
    problems = []
    for p in posts:
        if p["slot"] not in ACCOUNT.slots:
            problems.append(f"{p['slot']}：投稿時刻は {' / '.join(ACCOUNT.slots)} のどれかにしてください")
        for e in validate(Draft(slot=p["slot"], text=p["text"], reply=p.get("reply"))):
            problems.append(f"{p['slot']}：{e}")
    if len({p["slot"] for p in posts}) != len(posts):
        problems.append("同じ時刻の案が重複しています")
    return problems


def main(path: str) -> int:
    data = json.loads(Path(path).read_text())
    date_str, posts = data["date"], data["posts"]

    problems = check(posts)
    if problems:
        print("投稿案に問題があるため Issue を作りませんでした：")
        print("\n".join(f"- {x}" for x in problems))
        return 1

    if find_issue(date_str, ACCOUNT.slug):
        print(f"{ACCOUNT.display_name}：{date_str} の投稿案はすでにあります。重複して作りません。")
        return 0

    gh_api(
        "labels",
        "POST",
        {"name": LABEL, "color": "F9A825", "description": "承認待ちの投稿案"},
        ok_codes=(422, "already_exists"),
    )
    title, body = render(
        date_str, posts, account=ACCOUNT.slug, short_name="" if ACCOUNT.legacy else ACCOUNT.short_name
    )
    issue = gh_api("issues", "POST", {"title": title, "body": body, "labels": [LABEL]})
    print(f"投稿案を作成しました：{issue['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
