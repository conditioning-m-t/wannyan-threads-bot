"""承認済みの投稿案を、時刻になったら投稿する（GitHub Actions から実行）。

安全ルール（コードで強制）:
- 承認チェックが入った案だけ投稿する
- 1回の実行で投稿するのは1案まで、1日3案まで
- 時刻を90分過ぎた案は投稿せず「見送り」にする
- 1投稿目にURLを入れない（リンクはツリー2投稿目へ）
- Amazonリンクを含む案は、リンクの横に PR が必須
- 下書きの穴埋め記号（{{ }}）が残っていたら投稿しない
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import github_api as gh
from issue_format import LABEL, Draft, mark, parse

JST = timezone(timedelta(hours=9))
WINDOW = timedelta(minutes=90)
MAX_PER_DAY = 3
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# トピックを付けた投稿のほうが伸びやすい（Meta）。案にトピックがない時の既定値
DEFAULT_TOPIC = "ペットのいる暮らし"
URL_RE = re.compile(r"https?://|link\.amazon|amzn\.(to|asia)|a\.co/", re.IGNORECASE)
AMAZON_RE = re.compile(r"amazon\.co\.jp|link\.amazon|amzn\.(to|asia)|a\.co/", re.IGNORECASE)


def validate(d: Draft) -> list[str]:
    errors = []
    if len(d.text) > 500:
        errors.append(f"1投稿目が500文字を超えています（{len(d.text)}文字）")
    if d.reply and len(d.reply) > 500:
        errors.append(f"2投稿目が500文字を超えています（{len(d.reply)}文字）")
    if URL_RE.search(d.text):
        errors.append("1投稿目にURLが入っています。リンクはツリー2投稿目に移してください")
    if "{{" in d.text or (d.reply and "{{" in d.reply):
        errors.append("穴埋め記号 {{ }} が残っています")
    if d.topic and (len(d.topic) > 50 or "." in d.topic or "&" in d.topic):
        errors.append("トピックは50文字以内で、「.」「&」は使えません")
    if d.reply and AMAZON_RE.search(d.reply) and "PR" not in d.reply:
        errors.append("Amazonリンクを含む案ですが、ツリー2投稿目のリンクの横に PR がありません")
    return errors


def publish(d: Draft) -> str:
    from threads_api import get_me, get_permalink, publish_text

    user_id = get_me()["id"]
    main_id = publish_text(user_id, d.text, topic_tag=d.topic or DEFAULT_TOPIC)
    if d.reply:
        time.sleep(5)
        publish_text(user_id, d.reply, reply_to_id=main_id)
    return get_permalink(main_id)


def save(number: int, body: str) -> None:
    if DRY_RUN:
        return
    gh.update_body(number, body)


def note(number: int, text: str) -> None:
    print(text)
    if not DRY_RUN:
        gh.comment(number, text)


def process_issue(issue: dict, now: datetime) -> None:
    number = issue["number"]
    body = issue["body"] or ""
    parsed = parse(body)
    if not parsed:
        return
    today = now.date().isoformat()

    if parsed.date < today:
        if not DRY_RUN:
            gh.close(number)
        print(f"#{number}（{parsed.date}）は過去の日付なので閉じました")
        return
    if parsed.date > today:
        print(f"#{number}（{parsed.date}）はまだ先の日付です")
        return

    posted_count = sum(1 for d in parsed.drafts if d.status == "posted")
    posted_this_run = False

    for d in parsed.drafts:
        if d.status:
            continue
        hh, mm = map(int, d.slot.split(":"))
        slot_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < slot_dt:
            continue
        if now - slot_dt > WINDOW:
            reason = "未承認" if not d.approved else "承認が時刻に間に合わなかった"
            body = mark(body, d.slot, f"⏭ 見送り：{reason}")
            save(number, body)
            print(f"{d.slot} は見送り（{reason}）")
            continue
        if not d.approved:
            print(f"{d.slot} はまだ承認されていません（{int(WINDOW.total_seconds() // 60)}分まで待ちます）")
            continue
        if posted_this_run or posted_count >= MAX_PER_DAY:
            print(f"{d.slot} は投稿上限のため今回は見送り")
            continue

        errors = validate(d)
        if errors:
            body = mark(body, d.slot, "⚠️ エラーのため未投稿")
            save(number, body)
            note(number, f"⚠️ {d.slot} の案は投稿しませんでした。\n\n" + "\n".join(f"- {e}" for e in errors))
            continue

        if DRY_RUN:
            print(f"[DRY_RUN] {d.slot} を投稿します：\n{d.text}\n---\n{d.reply or '(ツリーなし)'}")
            posted_this_run = True
            continue

        try:
            permalink = publish(d)
        except Exception as e:  # noqa: BLE001
            body = mark(body, d.slot, "⚠️ エラーのため未投稿")
            save(number, body)
            note(number, f"⚠️ {d.slot} の投稿に失敗しました。\n\n```\n{e}\n```")
            continue

        body = mark(body, d.slot, "✅ 投稿済み")
        save(number, body)
        note(number, f"✅ {d.slot} の投稿を公開しました\n{permalink}")
        posted_this_run = True
        posted_count += 1

    if parsed.drafts and all(
        re.search(rf"{re.escape(d.slot)} を承認する（", body) for d in parsed.drafts
    ):
        if not DRY_RUN:
            gh.close(number)
        print(f"#{number} はすべて処理済みなので閉じました")


def main() -> int:
    now = datetime.now(JST)
    override = os.environ.get("NOW_JST")  # テスト用: 2026-10-20T07:05
    if override:
        now = datetime.fromisoformat(override).replace(tzinfo=JST)
    print(f"実行時刻（日本時間）：{now:%Y-%m-%d %H:%M}{'（テスト実行）' if DRY_RUN else ''}")
    issues = gh.open_issues(LABEL)
    if not issues:
        print("処理する投稿案はありません")
    for issue in issues:
        process_issue(issue, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
