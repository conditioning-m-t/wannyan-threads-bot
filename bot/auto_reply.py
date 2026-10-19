"""自分の投稿についたコメントに、Claude で考えた返信を自動で投稿する（GitHub Actions から実行）。

安全ルール（コードで強制）:
- 返信は1日50件まで、1回の実行で15件まで。返信と返信の間は15〜25秒あける
- 直近72時間の投稿のコメントだけが対象。一度処理したコメントには二度と触れない
- 返信文にURL・ハッシュタグ・商品名らしき語・長い英数字列（秘密情報の漏えい対策）があれば投稿しない
- Claude にはツールを一切使わせず、Threads のトークンも渡さない（コメント経由の悪用対策）
- 判断が必要なコメントは返信せず data/escalations.json に記録する
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from threads_api import ThreadsAPIError, get_me, list_my_threads, publish_text, _request

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "replied.json"
ESCALATIONS = ROOT / "data" / "escalations.json"
RULES = Path(__file__).resolve().parent / "reply_rules.md"

MAX_PER_DAY = 50
MAX_PER_RUN = 15
MAX_CLASSIFY = 30
LOOKBACK = timedelta(hours=72)

BAD_REPLY_RE = re.compile(
    r"https?://|www\.|#|amazon|amzn|link\.|[A-Za-z0-9_\-]{25,}|うちの(子|猫|犬|わんこ|にゃんこ)",
    re.IGNORECASE,
)


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def parse_ts(ts: str) -> datetime:
    # Threads の timestamp 例: 2026-10-20T07:03:12+0000
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def get_comments(media_id: str) -> list[dict]:
    res = _request(
        "GET",
        f"{media_id}/replies",
        {"fields": "id,text,username,timestamp,media_type,media_url,is_reply_owned_by_me"},
    )
    return res.get("data", [])


def validate_reply(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return "返信文が空"
    if len(text) > 150:
        return f"返信文が長すぎる（{len(text)}文字）"
    if BAD_REPLY_RE.search(text):
        return "返信文に使えない表現（URL・ハッシュタグ・宣伝・飼い主を名乗る表現など）が含まれる"
    return None


def ask_claude(items: list[dict]) -> list[dict]:
    prompt = (
        RULES.read_text()
        + "\n\n## 今回のコメント（JSON）\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + "\n\n上のルールに従い、すべてのコメントについてJSON配列だけを出力してください。"
    )
    # Threads・GitHub のトークンは渡さない
    env = {k: v for k, v in os.environ.items() if k not in ("THREADS_ACCESS_TOKEN", "GITHUB_TOKEN")}
    with tempfile.TemporaryDirectory() as tmp:
        res = subprocess.run(
            [
                "claude", "-p",
                "--tools", "",
                "--model", "sonnet",
                "--output-format", "text",
                "--no-session-persistence",
                "--strict-mcp-config",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tmp,
            env=env,
            timeout=600,
        )
    if res.returncode != 0:
        raise RuntimeError(f"Claude の実行に失敗しました：{res.stderr.strip()[:500]}")
    out = res.stdout
    start, end = out.find("["), out.rfind("]")
    if start < 0 or end < 0:
        raise RuntimeError(f"Claude の出力からJSONを読み取れませんでした：{out[:300]}")
    return json.loads(out[start : end + 1])


def main() -> int:
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and not os.environ.get("ANTHROPIC_API_KEY"):
        print("CLAUDE_CODE_OAUTH_TOKEN が未設定のため、自動返信は休止中です")
        return 0

    now = datetime.now(JST)
    today = now.date().isoformat()
    state = load(STATE, {"comments": {}})
    escalations = load(ESCALATIONS, {"items": []})
    done = state["comments"]

    replied_today = sum(
        1 for v in done.values() if v.get("action") == "reply" and v.get("at", "").startswith(today)
    )
    budget = min(MAX_PER_RUN, MAX_PER_DAY - replied_today)
    if budget <= 0:
        print(f"今日の返信は上限（{MAX_PER_DAY}件）に達しています")
        return 0

    me = get_me()
    posts = [
        p for p in list_my_threads(limit=15)
        if p.get("timestamp") and now - parse_ts(p["timestamp"]) <= LOOKBACK
    ]
    posts.sort(key=lambda p: p["timestamp"], reverse=True)  # 新しい投稿のコメントを優先

    pending: list[dict] = []
    for p in posts:
        try:
            comments = get_comments(p["id"])
        except ThreadsAPIError as e:
            print(f"コメントを取得できませんでした（{p['id']}）：{e}")
            continue
        for c in sorted(comments, key=lambda c: c.get("timestamp", "")):
            if c["id"] in done or c.get("is_reply_owned_by_me") or c.get("username") == me["username"]:
                continue
            if not c.get("timestamp") or now - parse_ts(c["timestamp"]) > LOOKBACK:
                continue
            pending.append(
                {
                    "id": c["id"],
                    "username": c.get("username", ""),
                    "comment": (c.get("text") or "")[:500],
                    "has_photo": c.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM", "VIDEO"),
                    "post_text": (p.get("text") or "")[:200],
                    "_post_permalink": p.get("permalink", ""),
                }
            )
    if not pending:
        print("新しいコメントはありません")
        return 0

    batch = pending[:MAX_CLASSIFY]
    print(f"新しいコメント {len(pending)}件のうち {len(batch)}件を処理します（今回の返信上限 {budget}件）")
    by_id = {c["id"]: c for c in batch}
    decisions = ask_claude([{k: v for k, v in c.items() if not k.startswith("_")} for c in batch])

    replied = 0
    stamp = lambda: datetime.now(JST).isoformat(timespec="seconds")  # noqa: E731
    for d in decisions:
        c = by_id.get(str(d.get("id")))
        if not c or c["id"] in done:
            continue
        action = d.get("action")
        if action == "reply":
            if replied >= budget:
                continue  # 上限に達した分は次回に回す（記録しない）
            problem = validate_reply(d.get("text", ""))
            if problem:
                done[c["id"]] = {"action": "skip", "reason": problem, "at": stamp()}
                print(f"見送り：@{c['username']}（{problem}）")
                continue
            if replied:
                time.sleep(random.uniform(15, 25))
            try:
                reply_id = publish_text(me["id"], d["text"].strip(), reply_to_id=c["id"])
            except ThreadsAPIError as e:
                print(f"返信に失敗：@{c['username']}：{e}")
                continue
            done[c["id"]] = {"action": "reply", "reply_id": reply_id, "at": stamp()}
            replied += 1
            print(f"返信：@{c['username']} ← {d['text'].strip()}")
        elif action == "escalate":
            done[c["id"]] = {"action": "escalate", "at": stamp()}
            escalations["items"].append(
                {
                    "comment_id": c["id"],
                    "username": c["username"],
                    "comment": c["comment"],
                    "post_text": c["post_text"],
                    "post_permalink": c["_post_permalink"],
                    "reason": d.get("reason", ""),
                    "at": stamp(),
                    "reported": False,
                }
            )
            print(f"報告に回す：@{c['username']}（{d.get('reason', '')}）")
        else:
            done[c["id"]] = {"action": "skip", "reason": d.get("reason", ""), "at": stamp()}

    save(STATE, state)
    save(ESCALATIONS, escalations)
    print(f"返信 {replied}件（今日の合計 {replied_today + replied}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
