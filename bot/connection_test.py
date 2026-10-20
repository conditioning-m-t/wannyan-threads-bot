"""接続テスト：トークンが正しく使えるかを確認する。投稿は一切しない。"""

from __future__ import annotations

import sys

import account
from threads_api import ThreadsAPIError, get_me, get_publishing_limit


def main() -> int:
    try:
        me = get_me()
        print(f"✅ 接続成功：@{me['username']}（ユーザーID {me['id']}）")
        limit = get_publishing_limit(me["id"])
        data = (limit.get("data") or [{}])[0]
        print(f"   直近24時間の投稿数：{data.get('quota_usage', '?')} / {data.get('config', {}).get('quota_total', '?')}")
        print(f"   直近24時間の返信数：{data.get('reply_quota_usage', '?')} / {data.get('reply_config', {}).get('quota_total', '?')}")
        expected = account.load().username
        if me["username"] != expected:
            print(f"⚠️ 想定（@{expected}）と違うアカウントにつながっています。トークンを発行し直してください。")
            return 1
        return 0
    except ThreadsAPIError as e:
        print(f"❌ 接続失敗：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
