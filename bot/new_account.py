"""新しいアカウントの一式を accounts/<アカウント名>/ に作る（立ち上げ係が使う）。

使い方:
  python bot/new_account.py kaden --genre "家電・ガジェット" --display-name "暮らし家電メモ" \
      --username kurashi_kaden --short-name 家電 --default-topic "家電のある暮らし"

- 作ったアカウントは停止中（enabled: false）。オーナーの登録が終わり、接続テストに合格してから稼働中にする
- 運用ルール・返信ルールの「（ここに書く）」は、立ち上げ係がリサーチをもとに埋める
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account  # noqa: E402

TEMPLATES = account.ROOT / "templates" / "account"


def fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace(f"__{k}__", v)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="アカウント名（英小文字・数字・_）。シークレット名にも使う")
    ap.add_argument("--genre", required=True)
    ap.add_argument("--display-name", required=True)
    ap.add_argument("--username", required=True, help="Threadsのユーザー名（@なし）。未定なら候補")
    ap.add_argument("--short-name", required=True, help="投稿案ページの見出しに付ける短い名前")
    ap.add_argument("--default-topic", required=True)
    ap.add_argument("--slots", nargs=3, default=["07:00", "12:00", "21:00"])
    ap.add_argument("--tone", default="（ここに書く）")
    ap.add_argument("--profile", default="（ここに書く）\n※PRを含みます／投稿はAIで作成しています")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]{1,20}", args.slug):
        print("アカウント名は英小文字で始まる、英小文字・数字・_ の2〜21文字にしてください")
        return 1
    base = account.ACCOUNTS / args.slug
    if base.exists():
        print(f"accounts/{args.slug}/ はすでにあります")
        return 1
    others = {a.slug: a.username for a in account.all_accounts()}
    if args.username.lstrip("@") in others.values():
        print(f"@{args.username} はすでにほかのアカウントで使われています")
        return 1
    if "※PRを含みます" not in args.profile:
        print("プロフィール文には「※PRを含みます」を入れてください")
        return 1

    username = args.username.lstrip("@")
    secret = f"THREADS_ACCESS_TOKEN_{args.slug.upper()}"
    values = {
        "SLUG": args.slug,
        "GENRE": args.genre,
        "DISPLAY_NAME": args.display_name,
        "USERNAME": username,
        "DEFAULT_TOPIC": args.default_topic,
        "SLOT1": args.slots[0],
        "SLOT2": args.slots[1],
        "SLOT3": args.slots[2],
        "TONE": args.tone,
        "SECRET": secret,
        "PROFILE": args.profile,
        "GENRE_REPLY_NOTES": "### このジャンルならではの返し方\n（ここに書く）",
        "GENRE_ESCALATE": "- （ここに書く：このジャンルで慎重な対応が必要な話題）",
    }

    (base / "data").mkdir(parents=True)
    (base / "drafts").mkdir()
    (base / "data" / ".gitkeep").write_text("")
    (base / "drafts" / ".gitkeep").write_text("")
    cfg = {
        "username": username,
        "display_name": args.display_name,
        "short_name": args.short_name,
        "genre": args.genre,
        "enabled": False,
        "slots": args.slots,
        "max_per_day": 3,
        "default_topic": args.default_topic,
        "report": "summary",
    }
    (base / "account.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    (base / "products.json").write_text(
        json.dumps(
            {
                "_説明": "商品投稿に使ってよい商品とAmazonアソシエイトのリンクの一覧。リンクは田代さんがSiteStripeで作ったものだけを使う。factsには出典を確認できた事実だけを書く。",
                "products": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    for name, out in [("rules.md", "rules.md"), ("reply_rules.md", "reply_rules.md"), ("owner_guide.md", "立ち上げ手順.md")]:
        (base / out).write_text(fill((TEMPLATES / name).read_text(), values))
    (base / "商品候補.md").write_text(
        f"# {args.display_name}：Amazonの定番商品の候補\n\n"
        "田代さんがリンクを作る候補です。リンクができたら、商品名と一緒にチャットに貼ってください。\n\n"
        "| 商品のジャンル | 例（型番は目安） | 合う投稿の場面 | 確認した出典 |\n|---|---|---|---|\n"
    )
    print(f"accounts/{args.slug}/ を作りました（停止中）。シークレット名：{secret}")
    print("次は、運用ルール・返信ルールの「（ここに書く）」と、商品候補・最初の1週間分の案を作ってください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
