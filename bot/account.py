"""アカウントごとの設定と、ファイルの置き場所。

どのアカウントとして動くかは環境変数 ACCOUNT で決める（例：ACCOUNT=wannyan）。
設定は accounts/<アカウント名>/account.json に置く。

移行前からあるペットのアカウント（wannyan）は、accounts/wannyan/ がまだ無いあいだは
今までの場所（data/・drafts/・products.json・bot/reply_rules.md）を使う。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = ROOT / "accounts"
LEGACY = "wannyan"

LEGACY_CONFIG = {
    "username": "wannyan_pick",
    "display_name": "わんにゃん暮らしの便利帖",
    "short_name": "ペット",
    "enabled": True,
    "slots": ["07:00", "12:00", "21:00"],
    "max_per_day": 3,
    "default_topic": "ペットのいる暮らし",
    "report": "full",
}


@dataclass
class Account:
    slug: str
    username: str
    display_name: str
    base: Path
    legacy: bool = False
    short_name: str = ""
    enabled: bool = False
    slots: list[str] = field(default_factory=lambda: ["07:00", "12:00", "21:00"])
    max_per_day: int = 3
    default_topic: str = ""
    report: str = "summary"  # full=チャットに全文 / summary=要約だけ
    # 攻めモード：最初のコメントへの返信でもフォローをお願いする（同じ人には1回まで）
    follow_push: bool = False

    def path(self, name: str) -> Path:
        """アカウント専用のファイル（例：data/replied.json、drafts、products.json、reply_rules.md）。"""
        if self.legacy and name == "reply_rules.md":
            return ROOT / "bot" / "reply_rules.md"
        return self.base / name

    @property
    def secret_name(self) -> str:
        return f"THREADS_ACCESS_TOKEN_{self.slug.upper()}"


def load(slug: str | None = None) -> Account:
    slug = slug or os.environ.get("ACCOUNT") or LEGACY
    cfg_path = ACCOUNTS / slug / "account.json"
    if cfg_path.exists():
        cfg, base, legacy = json.loads(cfg_path.read_text()), cfg_path.parent, False
    elif slug == LEGACY:
        cfg, base, legacy = LEGACY_CONFIG, ROOT, True
    else:
        raise SystemExit(f"アカウント「{slug}」の設定（accounts/{slug}/account.json）がありません")
    known = {k: v for k, v in cfg.items() if k in Account.__dataclass_fields__ and k not in ("slug", "base", "legacy")}
    return Account(slug=slug, base=base, legacy=legacy, **known)


def all_accounts(enabled_only: bool = False) -> list[Account]:
    slugs = sorted(p.parent.name for p in ACCOUNTS.glob("*/account.json"))
    if LEGACY not in slugs:
        slugs.insert(0, LEGACY)
    accounts = [load(s) for s in slugs]
    return [a for a in accounts if a.enabled] if enabled_only else accounts


if __name__ == "__main__":
    # Actions から呼ぶ：アカウントごとに並列で動かすための一覧（JSON）を出す
    #   all … 停止中のアカウントも含める（接続テスト・合鍵の更新用）
    #   new … accounts/ にあるアカウントだけ（ペットは専用の自動実行で動くので除く）
    import sys

    opts = set(sys.argv[1:])
    rows = [
        {"account": a.slug, "secret": a.secret_name}
        for a in all_accounts(enabled_only="all" not in opts)
        if not ("new" in opts and a.legacy)
    ]
    print(json.dumps({"include": rows}))
