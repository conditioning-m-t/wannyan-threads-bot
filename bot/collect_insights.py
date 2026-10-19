"""直近の投稿の反応（表示数・いいね・返信など）を data/insights.json に保存する。

下書きを作るときに「どの型が伸びたか」を判断する材料にする。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from threads_api import ThreadsAPIError, get_media_insights, list_my_threads

JST = timezone(timedelta(hours=9))
OUT = Path(__file__).resolve().parent.parent / "data" / "insights.json"


def main() -> int:
    posts = []
    for t in list_my_threads(limit=40):
        if t.get("media_type") == "REPOST_FACADE":
            continue
        try:
            metrics = get_media_insights(t["id"])
        except ThreadsAPIError as e:
            print(f"反応データを取れませんでした（{t['id']}）：{e}")
            metrics = {}
        posts.append(
            {
                "id": t["id"],
                "timestamp": t.get("timestamp"),
                "permalink": t.get("permalink"),
                "text": (t.get("text") or "")[:300],
                **metrics,
            }
        )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"updated_at": datetime.now(JST).isoformat(timespec="minutes"), "posts": posts},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"{len(posts)}件の投稿の反応を保存しました")
    top = sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:3]
    for p in top:
        print(f"  表示{p.get('views', 0)} いいね{p.get('likes', 0)} 返信{p.get('replies', 0)}｜{p['text'][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
