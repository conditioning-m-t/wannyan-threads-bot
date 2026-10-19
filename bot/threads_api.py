"""Threads API の最小クライアント（標準ライブラリのみ）。

アクセストークンは環境変数 THREADS_ACCESS_TOKEN から読み込む。
トークンの値は絶対にログへ出さないこと。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://graph.threads.net/v1.0"


class ThreadsAPIError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise ThreadsAPIError(
            "THREADS_ACCESS_TOKEN が設定されていません。"
            "GitHub の Settings > Secrets and variables > Actions で登録してください。"
        )
    return token


def _request(method: str, path: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    params["access_token"] = _token()
    url = f"{BASE_URL}/{path.lstrip('/')}"
    data = None
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode(params)}"
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # エラー本文にはトークンは含まれないが、念のため伏せ字にする
        body = body.replace(params["access_token"], "***")
        raise ThreadsAPIError(f"HTTP {e.code}: {body}") from None


def get_me() -> dict:
    return _request("GET", "me", {"fields": "id,username"})


def get_publishing_limit(user_id: str) -> dict:
    return _request(
        "GET",
        f"{user_id}/threads_publishing_limit",
        {"fields": "quota_usage,config,reply_quota_usage,reply_config"},
    )


def publish_text(user_id: str, text: str, reply_to_id: str | None = None) -> str:
    """テキスト投稿（または返信）を公開し、投稿IDを返す。"""
    if len(text) > 500:
        raise ThreadsAPIError(f"500文字を超えています（{len(text)}文字）")
    params = {"media_type": "TEXT", "text": text}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    container = _request("POST", f"{user_id}/threads", params)
    creation_id = container["id"]

    # コンテナの準備完了を待つ（テキストは通常すぐ終わる）
    for _ in range(10):
        status = _request("GET", creation_id, {"fields": "status,error_message"})
        if status.get("status") == "FINISHED":
            break
        if status.get("status") == "ERROR":
            raise ThreadsAPIError(f"投稿の準備に失敗: {status.get('error_message')}")
        time.sleep(3)

    published = _request("POST", f"{user_id}/threads_publish", {"creation_id": creation_id})
    return published["id"]


def get_permalink(media_id: str) -> str:
    return _request("GET", media_id, {"fields": "permalink"}).get("permalink", "")


def list_my_threads(limit: int = 25) -> list[dict]:
    res = _request(
        "GET",
        "me/threads",
        {"fields": "id,text,timestamp,permalink,media_type", "limit": str(limit)},
    )
    return res.get("data", [])


def get_media_insights(media_id: str) -> dict:
    res = _request(
        "GET",
        f"{media_id}/insights",
        {"metric": "views,likes,replies,reposts,quotes"},
    )
    out = {}
    for item in res.get("data", []):
        values = item.get("values") or [{}]
        out[item["name"]] = values[0].get("value", 0)
    return out


def get_replies(media_id: str) -> list[dict]:
    res = _request(
        "GET",
        f"{media_id}/replies",
        {"fields": "id,text,username,timestamp,media_type,media_url"},
    )
    return res.get("data", [])
