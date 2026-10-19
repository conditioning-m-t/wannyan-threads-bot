"""チャットでの承認・修正を、承認用Issueに反映する。

使い方:
  python bot/approve.py 2026-10-20 --show                      今の状態を表示
  python bot/approve.py 2026-10-20 --approve 07:00 21:00       指定の案を承認
  python bot/approve.py 2026-10-20 --approve all               全部承認
  python bot/approve.py 2026-10-20 --unapprove 12:00           承認を取り消す
  python bot/approve.py 2026-10-20 --sync drafts/2026-10-20.json
      下書きJSONを直したあと、まだ投稿していない案の本文をIssueに反映する
（--sync と --approve は同時に指定できる。sync が先に実行される）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_draft_issue import check  # noqa: E402
from gh_cli import find_issue, gh_api  # noqa: E402
from issue_format import parse  # noqa: E402

JST = timezone(timedelta(hours=9))
STATUS_JA = {"posted": "✅投稿済み", "skipped": "⏭見送り", "error": "⚠️エラー", "": ""}
REPLY_INTRO = "ツリー2投稿目（自分の投稿への返信として続けて投稿されます）"


def show(body: str) -> None:
    parsed = parse(body)
    for d in parsed.drafts:
        state = STATUS_JA[d.status] or ("承認済み" if d.approved else "未承認")
        print(f"■ {d.slot}［{state}］\n{d.text}")
        if d.reply:
            print(f"  └ ツリー2投稿目：{d.reply}")
        print()


def sync(body: str, posts: list[dict]) -> str:
    parsed = {d.slot: d for d in parse(body).drafts}
    for p in posts:
        slot = p["slot"]
        d = parsed.get(slot)
        if d is None:
            print(f"{slot}：Issueにない時刻なので反映しませんでした")
            continue
        if d.status:
            print(f"{slot}：すでに処理済み（{STATUS_JA[d.status]}）なので変更しませんでした")
            continue
        s = re.escape(slot)
        body = re.sub(
            rf"(<!-- post {s} -->\s*\n```text\n).*?(\n```)",
            lambda m: m.group(1) + p["text"].strip() + m.group(2),
            body,
            count=1,
            flags=re.DOTALL,
        )
        reply_re = re.compile(
            rf"(?:{re.escape(REPLY_INTRO)}\n\n)?<!-- reply {s} -->\s*\n```text\n.*?\n```\n?", re.DOTALL
        )
        body = reply_re.sub("", body, count=1)
        if p.get("reply"):
            block = f"\n{REPLY_INTRO}\n\n<!-- reply {slot} -->\n```text\n{p['reply'].strip()}\n```\n"
            body = re.sub(
                rf"(<!-- post {s} -->\s*\n```text\n.*?\n```\n)",
                lambda m: m.group(1) + block,
                body,
                count=1,
                flags=re.DOTALL,
            )
        body = re.sub(rf"<!-- topic {s} .+? -->\nトピック：.*\n\n", "", body, count=1)
        if p.get("topic"):
            body = re.sub(
                rf"(^- \[[ xX]\] {s} を承認する.*\n\n)",
                lambda m: m.group(1) + f"<!-- topic {slot} {p['topic'].strip()} -->\nトピック：{p['topic'].strip()}\n\n",
                body,
                count=1,
                flags=re.MULTILINE,
            )
        print(f"{slot}：本文を更新しました")
    return body


def set_approval(body: str, slots: list[str], approve: bool, date_str: str) -> str:
    parsed = {d.slot: d for d in parse(body).drafts}
    if slots == ["all"]:
        slots = list(parsed)
    now = datetime.now(JST)
    for slot in slots:
        d = parsed.get(slot)
        if d is None:
            print(f"{slot}：その時刻の案はありません")
            continue
        if d.status:
            print(f"{slot}：すでに処理済み（{STATUS_JA[d.status]}）です")
            continue
        hh, mm = map(int, slot.split(":"))
        slot_dt = datetime.fromisoformat(date_str).replace(hour=hh, minute=mm, tzinfo=JST)
        if approve and now > slot_dt + timedelta(minutes=90):
            print(f"{slot}：投稿時刻を90分以上過ぎているため、承認しても投稿されません")
            continue
        new = "[x]" if approve else "[ ]"
        body = re.sub(
            rf"^- \[[ xX]\] {re.escape(slot)} を承認する",
            f"- {new} {slot} を承認する",
            body,
            count=1,
            flags=re.MULTILINE,
        )
        print(f"{slot}：{'承認しました' if approve else '承認を取り消しました'}")
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--approve", nargs="+")
    ap.add_argument("--unapprove", nargs="+")
    ap.add_argument("--sync")
    args = ap.parse_args()

    issue = find_issue(args.date)
    if not issue:
        print(f"{args.date} の投稿案（未完了のもの）が見つかりません")
        return 1
    body = original = issue["body"] or ""

    if args.sync:
        posts = json.loads(Path(args.sync).read_text())["posts"]
        problems = check(posts)
        if problems:
            print("下書きに問題があるため反映しませんでした：")
            print("\n".join(f"- {x}" for x in problems))
            return 1
        body = sync(body, posts)
    if args.approve:
        body = set_approval(body, args.approve, True, args.date)
    if args.unapprove:
        body = set_approval(body, args.unapprove, False, args.date)

    if body != original:
        gh_api(f"issues/{issue['number']}", "PATCH", {"body": body})
        print(f"Issue #{issue['number']} を更新しました：{issue['html_url']}")
    if args.show or body != original:
        print()
        show(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
