"""反応の良かった型・悪かった型を調べる（毎晩の案づくりで、案を作る前に使う）。

使い方:
  python bot/performance.py wannyan        ペット
  python bot/performance.py kaji           ほかのアカウント（accounts/ の名前）
  python bot/performance.py kaji --days 21 調べる日数を変える（ふだんは直近21日）

2026-11-07 オーナー指示（全アカウント共通）：
  いいねやコメントが多くついた投稿の型・性格を見習って新しい案を作る。反応がなかった型・性格の投稿はしない。

やること:
- 反応データ（data/insights.json）と投稿案（drafts/）を本文でつなぎ、投稿ごとの「型」（案の type）を調べる
- 反応 = いいね + コメント。アカウントの中で比べる（ほかのアカウントとは比べない）
- 「見習う投稿」：反応が上位の投稿（本文つき）
- 「見習う型」：平均の反応が全体の平均以上の型
- 「使わない型」：2本以上出して、どれも反応がとても少なかった型（全体の平均の4分の1未満）
  → bot/check_drafts.py が、この型の案に ⚠️ を出す
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account  # noqa: E402

JST = timezone(timedelta(hours=9))
DAYS = 21
LOW_RATIO = 0.25  # 全体の平均のこれ未満を「反応がとても少ない」とする
TOP_N = 5


def key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text)[:30]


def type_of(post: dict) -> str:
    """案の type から、くらべやすい「型」の名前を取り出す。商品投稿は「商品」にまとめる。"""
    t = (post.get("type") or "").strip()
    if post.get("reply") and re.search(r"https?://", post["reply"]):
        return "商品"
    m = re.search(r"（(.+?)）", t)
    inner = m.group(1) if m else t
    return inner or "（型の記録なし）"


def collect(acc: account.Account, days: int = DAYS) -> list[dict]:
    insights_path = acc.path("data/insights.json")
    if not insights_path.exists():
        return []
    raw = json.loads(insights_path.read_text())
    posts = raw["posts"] if isinstance(raw, dict) else raw
    since = datetime.now(JST).date() - timedelta(days=days)

    drafts: dict[str, dict] = {}
    for f in sorted(acc.path("drafts").glob("*.json")):
        try:
            for p in json.loads(f.read_text()).get("posts", []):
                drafts[key(p.get("text", ""))] = p
        except (ValueError, KeyError):
            continue

    rows = []
    for x in posts:
        ts = datetime.fromisoformat(x["timestamp"].replace("+0000", "+00:00")).astimezone(JST)
        if ts.date() < since:
            continue
        d = drafts.get(key(x.get("text", "")))
        rows.append({
            "at": ts.strftime("%m/%d %H:%M"),
            "type": type_of(d) if d else "（手動の投稿・型の記録なし）",
            "text": (x.get("text") or "").strip(),
            "views": x.get("views", 0),
            "likes": x.get("likes", 0),
            "replies": x.get("replies", 0),
            "score": x.get("likes", 0) + x.get("replies", 0),
        })
    return rows


def analyze(acc: account.Account, days: int = DAYS) -> dict:
    rows = collect(acc, days)
    if not rows:
        return {"rows": [], "avg": 0, "good": [], "bad": [], "top": [], "bottom": []}
    avg = sum(r["score"] for r in rows) / len(rows)
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    stats = []
    for t, rs in by_type.items():
        a = sum(r["score"] for r in rs) / len(rs)
        stats.append({"type": t, "n": len(rs), "avg": a, "max": max(r["score"] for r in rs)})
    stats.sort(key=lambda s: -s["avg"])
    good = [s for s in stats if s["avg"] >= avg and not s["type"].startswith("（")]
    bad = [
        s for s in stats
        if s["n"] >= 2 and s["max"] < max(avg * LOW_RATIO, 1) and not s["type"].startswith("（")
    ]
    ranked = sorted(rows, key=lambda r: -r["score"])
    return {"rows": rows, "avg": avg, "stats": stats, "good": good, "bad": bad,
            "top": ranked[:TOP_N], "bottom": [r for r in ranked[::-1] if r["score"] <= avg * LOW_RATIO][:TOP_N]}


def bad_types(acc: account.Account) -> set[str]:
    return {s["type"] for s in analyze(acc)["bad"]}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    days = DAYS
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
        args = [a for a in args if a != str(days)]
    acc = account.load(args[0] if args else None)
    res = analyze(acc, days)
    print(f"■ {acc.display_name}（@{acc.username}）直近{days}日・{len(res['rows'])}本・反応（いいね＋コメント）の平均 {res['avg']:.1f}")
    if not res["rows"]:
        print("  反応データがまだありません")
        return 0
    print("\n【見習う投稿】反応が多かった順")
    for r in res["top"]:
        print(f"  {r['score']:>5}（いいね{r['likes']}・コメント{r['replies']}・表示{r['views']}）［{r['type']}］{r['at']}")
        print("        " + r["text"].replace("\n", " / ")[:80])
    print("\n【見習う型】平均以上")
    for s in res["good"]:
        print(f"  {s['type']}：平均{s['avg']:.1f}（{s['n']}本）")
    print("\n【使わない型】2本以上出して、どれも反応がとても少なかった")
    for s in res["bad"] or []:
        print(f"  {s['type']}：平均{s['avg']:.1f}・最高{s['max']}（{s['n']}本）")
    if not res["bad"]:
        print("  （なし）")
    print("\n【反応がとても少なかった投稿】同じ切り口・性格は使わない")
    for r in res["bottom"]:
        print(f"  {r['score']:>5}（表示{r['views']}）［{r['type']}］{r['at']} " + r["text"].replace("\n", " / ")[:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
