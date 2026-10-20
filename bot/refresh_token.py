"""合鍵（Threadsの長期トークン、約60日）を延長し、GitHubのシークレットに書き戻す（GitHub Actions から実行）。

- 延長は grant_type=th_refresh_token。発行から24時間以上たち、期限が切れていない合鍵だけ延長できる
- 書き戻しには、オーナーが一度だけ登録する「シークレットを書き換えてよい合鍵」（SECRETS_WRITER_TOKEN）を使う。
  未登録なら何もしない
- 新しい合鍵が正しいアカウントのものか確かめてから書き戻す
- 合鍵の値は画面・ログ・ファイルに一切出さない。結果（期限の日付だけ）を data/token_status.json に残す
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import account

JST = timezone(timedelta(hours=9))
ACCOUNT = account.load()
STATUS = ACCOUNT.path("data/token_status.json")
REFRESH_URL = "https://graph.threads.net/refresh_access_token"


def get_json(url: str, headers: dict | None = None) -> tuple[dict, dict]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode()), dict(res.headers)


def writer_expiration(repo: str, writer: str) -> str:
    """書き換え用の合鍵の有効期限（GitHubが応答に付けてくる）。無期限なら空。"""
    try:
        _, headers = get_json(
            f"https://api.github.com/repos/{repo}",
            {"Authorization": f"Bearer {writer}", "Accept": "application/vnd.github+json"},
        )
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ 書き換え用の合鍵が使えません（HTTP {e.code}）。発行し直してください") from None
    for k, v in headers.items():
        if k.lower() == "github-authentication-token-expiration":
            return v
    return ""


def save_status(**fields) -> None:
    status = {"secret": ACCOUNT.secret_name, "checked_at": datetime.now(JST).isoformat(timespec="minutes"), **fields}
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    writer = os.environ.get("SECRETS_WRITER_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not writer:
        print("書き換え用の合鍵（SECRETS_WRITER_TOKEN）が未登録のため、自動更新は休止中です")
        return 0
    current = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not current:
        print(f"{ACCOUNT.secret_name} が未登録のため、@{ACCOUNT.username} の合鍵は更新しません")
        return 0

    writer_expires = writer_expiration(repo, writer)
    query = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": current})
    try:
        res, _ = get_json(f"{REFRESH_URL}?{query}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace").replace(current, "***")
        save_status(ok=False, error=f"延長に失敗（HTTP {e.code}）", writer_expires=writer_expires)
        print(f"❌ @{ACCOUNT.username} の合鍵を延長できませんでした（HTTP {e.code}）：{body[:300]}")
        return 1
    new = res["access_token"]
    print(f"::add-mask::{new}")  # 万一どこかに出ても伏せ字になるようにする

    # 新しい合鍵が、このアカウントのものか確かめる
    me, _ = get_json(
        "https://graph.threads.net/v1.0/me?" + urllib.parse.urlencode({"fields": "username", "access_token": new})
    )
    if me.get("username") != ACCOUNT.username:
        save_status(ok=False, error="延長した合鍵のアカウント名が設定と違う", writer_expires=writer_expires)
        print(f"❌ 延長した合鍵が別のアカウント（@{me.get('username')}）のものなので、書き戻しませんでした")
        return 1

    env = {**os.environ, "GH_TOKEN": writer}
    env.pop("GITHUB_TOKEN", None)
    done = subprocess.run(
        ["gh", "secret", "set", ACCOUNT.secret_name, "--repo", repo],
        input=new, text=True, capture_output=True, env=env,
    )
    if done.returncode != 0:
        save_status(ok=False, error="シークレットへの書き戻しに失敗", writer_expires=writer_expires)
        print(f"❌ シークレットに書き戻せませんでした：{(done.stderr or '').replace(new, '***')[:300]}")
        return 1

    expires = datetime.now(JST) + timedelta(seconds=int(res.get("expires_in", 0)))
    save_status(ok=True, refreshed_at=datetime.now(JST).isoformat(timespec="minutes"),
                expires_at=expires.date().isoformat(), writer_expires=writer_expires)
    print(f"✅ @{ACCOUNT.username} の合鍵を延長しました（次の期限：{expires:%Y-%m-%d}）")
    if writer_expires:
        print(f"   書き換え用の合鍵の期限：{writer_expires}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
