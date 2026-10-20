"""投稿案の自動チェック（毎晩の案づくり・立ち上げ係で使う）。

使い方:
  python bot/check_drafts.py 2026-10-21              稼働中の全アカウントの、その日の案を調べる
  python bot/check_drafts.py 2026-10-21 kaden        指定のアカウントだけ（停止中でも可）
  python bot/check_drafts.py 2026-10-21 --summary    要約報告用に、時刻・種類・狙いも出す

調べること:
- 形式（時刻・文字数・1投稿目のURL・PR表記・トピック・穴埋め記号）… 問題があれば ❌（Issueは作れない）
- 商品リンクが、そのアカウントの products.json にあるものか … ❌
- 絵文字が3個以上 … ⚠️
- 同じアカウントの直近14日の案と似すぎていないか … ⚠️
- ほかのアカウントの直近14日の案と似すぎていないか、1行目が同じでないか … ⚠️（BAN対策：似た投稿の量産をしない）
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account  # noqa: E402
from issue_format import Draft  # noqa: E402
from post_scheduled import validate  # noqa: E402

LOOKBACK_DAYS = 14
SIMILAR_SAME = 0.6   # 同じアカウントの過去の案との類似度の目安
SIMILAR_OTHER = 0.5  # ほかのアカウントとの類似度の目安（こちらを厳しめにする）
URL_RE = re.compile(r"https?://\S+")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s。、！？!?…・「」『』（）()〜~ー\-]+", "", text)


def first_line(text: str) -> str:
    return norm((text or "").strip().split("\n")[0])


def count_emoji(text: str) -> int:
    return sum(1 for ch in text or "" if unicodedata.category(ch) == "So" or 0x1F300 <= ord(ch) <= 0x1FAFF)


def load_posts(acc: account.Account, day: date) -> list[dict]:
    f = acc.path(f"drafts/{day.isoformat()}.json")
    if not f.exists():
        return []
    return json.loads(f.read_text()).get("posts", [])


def history(acc: account.Account, day: date, include_today: bool) -> list[tuple[str, dict]]:
    out = []
    for i in range(0 if include_today else 1, LOOKBACK_DAYS + 1):
        d = day - timedelta(days=i)
        out += [(d.isoformat(), p) for p in load_posts(acc, d)]
    return out


def check_account(acc: account.Account, day: date, others: list[account.Account]) -> tuple[list[str], list[str]]:
    posts = load_posts(acc, day)
    errors: list[str] = []
    warns: list[str] = []
    if not posts:
        return [f"{day} の案（drafts/{day}.json）がありません"], []

    links = {p.get("link", "") for p in json.loads(acc.path("products.json").read_text()).get("products", [])}
    if len({p["slot"] for p in posts}) != len(posts):
        errors.append("同じ時刻の案が重複しています")
    past = history(acc, day, include_today=False)
    other_posts = [(o.slug, d, p) for o in others for d, p in history(o, day, include_today=True)]

    for p in posts:
        slot = p.get("slot", "?")
        if slot not in acc.slots:
            errors.append(f"{slot}：投稿時刻は {' / '.join(acc.slots)} のどれかにしてください")
        errors += [f"{slot}：{e}" for e in validate(Draft(slot=slot, text=p.get("text", ""), reply=p.get("reply"), topic=p.get("topic") or ""))]
        if not p.get("topic"):
            warns.append(f"{slot}：トピックがありません（既定の「{acc.default_topic}」になります）")
        for url in URL_RE.findall(p.get("reply") or ""):
            if url not in links:
                errors.append(f"{slot}：products.json にないリンクです（{url}）")
        n = count_emoji(p.get("text", ""))
        if n > 2:
            warns.append(f"{slot}：絵文字が{n}個あります（2個まで）")

        text = norm(p.get("text", ""))
        for d, q in past:
            r = SequenceMatcher(None, text, norm(q.get("text", ""))).ratio()
            if r >= SIMILAR_SAME:
                warns.append(f"{slot}：{d} {q.get('slot')} の案と似ています（類似度 {r:.0%}）")
        for slug, d, q in other_posts:
            r = SequenceMatcher(None, text, norm(q.get("text", ""))).ratio()
            if r >= SIMILAR_OTHER:
                warns.append(f"{slot}：ほかのアカウント（{slug}）の {d} {q.get('slot')} の案と似ています（類似度 {r:.0%}）")
            elif first_line(p.get("text", "")) == first_line(q.get("text", "")):
                warns.append(f"{slot}：ほかのアカウント（{slug}）の {d} {q.get('slot')} の案と1行目が同じです")
    return errors, warns


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    summary = "--summary" in sys.argv
    if not args:
        print(__doc__)
        return 1
    day = date.fromisoformat(args[0])
    everyone = account.all_accounts()
    targets = [account.load(s) for s in args[1:]] or [a for a in everyone if a.enabled]

    failed = False
    for acc in targets:
        others = [o for o in everyone if o.slug != acc.slug]
        errors, warns = check_account(acc, day, others)
        mark = "❌" if errors else ("⚠️" if warns else "✅")
        print(f"{mark} {acc.display_name}（@{acc.username}）")
        if summary:
            for p in load_posts(acc, day):
                print(f"   {p.get('slot')}｜{p.get('type', '')}｜{p.get('memo', '')}")
        for e in errors:
            print(f"   ❌ {e}")
        for w in warns:
            print(f"   ⚠️ {w}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
