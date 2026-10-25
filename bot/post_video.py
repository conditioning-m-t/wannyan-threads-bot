"""video_posts/*.json にある「未投稿」の動画を1本、Threadsに投稿する（GitHub Actions から実行）。

ファイルの形式:
{
  "account": "wannyan",
  "video": "media/2026-10-25_papa-mama-dog.mp4",
  "text": "1投稿目の本文（URLなし・500文字以内）",
  "topic": "犬のいる暮らし",
  "status": "pending"
}
投稿後は status が "posted"（失敗なら "error"）になり、permalink / posted_at / error が書き足される。

安全ルール（コードで強制）:
- status が pending のものだけ、1回の実行で1本まで
- 1投稿目にURLを入れない、500文字以内
- 合鍵のアカウント名が設定と違えば投稿しない
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import account

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "video_posts"
ACCOUNT = account.load()
DRY_RUN = os.environ.get("DRY_RUN") == "1"
URL_RE = re.compile(r"https?://|link\.amazon|amzn\.(to|asia)|a\.co/", re.IGNORECASE)


def validate(item: dict) -> list[str]:
    errors = []
    text = item.get("text", "")
    if not text:
        errors.append("本文が空です")
    if len(text) > 500:
        errors.append(f"本文が500文字を超えています（{len(text)}文字）")
    if URL_RE.search(text):
        errors.append("本文にURLが入っています")
    video = item.get("video", "")
    if not video or not (ROOT / video).is_file():
        errors.append(f"動画ファイルが見つかりません：{video}")
    topic = item.get("topic") or ""
    if topic and (len(topic) > 50 or "." in topic or "&" in topic):
        errors.append("トピックは50文字以内で、「.」「&」は使えません")
    return errors


def video_url(path: str) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    ref = os.environ.get("GITHUB_SHA") or "main"
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def main() -> int:
    files = sorted(QUEUE.glob("*.json"))
    for f in files:
        item = json.loads(f.read_text())
        if item.get("status") != "pending" or item.get("account", account.LEGACY) != ACCOUNT.slug:
            continue
        errors = validate(item)
        if errors:
            item.update(status="error", error=" / ".join(errors))
            f.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
            print(f"⚠️ {f.name} は投稿しませんでした：{item['error']}")
            return 1
        url = video_url(item["video"])
        if DRY_RUN:
            print(f"[DRY_RUN] {f.name} を投稿します：{url}\n{item['text']}")
            return 0

        from threads_api import get_me, get_permalink, publish_video

        me = get_me()
        if me["username"] != ACCOUNT.username:
            raise SystemExit(f"合鍵が別のアカウント（@{me['username']}）のものです")
        try:
            media_id = publish_video(me["id"], url, item["text"], topic_tag=item.get("topic") or ACCOUNT.default_topic)
        except Exception as e:  # noqa: BLE001
            item.update(status="error", error=str(e)[:500])
            f.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
            print(f"⚠️ {f.name} の投稿に失敗しました：{e}")
            return 1
        link = ""
        try:
            link = get_permalink(media_id)
        except Exception:  # noqa: BLE001
            pass
        item.update(status="posted", media_id=media_id, permalink=link,
                    posted_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"))
        f.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
        print(f"✅ {f.name} を投稿しました {link}")
        return 0
    print("未投稿の動画はありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
