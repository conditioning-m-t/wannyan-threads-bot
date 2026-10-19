"""GitHub Actions 内で Issue を読み書きする最小クライアント。"""

from __future__ import annotations

import json
import os
import urllib.request


def _req(method: str, path: str, payload: dict | None = None):
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read().decode()
        return json.loads(raw) if raw else None


def open_issues(label: str) -> list[dict]:
    from urllib.parse import quote

    issues = _req("GET", f"issues?state=open&labels={quote(label)}&per_page=50") or []
    return [i for i in issues if "pull_request" not in i]


def update_body(number: int, body: str) -> None:
    _req("PATCH", f"issues/{number}", {"body": body})


def comment(number: int, text: str) -> None:
    _req("POST", f"issues/{number}/comments", {"body": text})


def close(number: int) -> None:
    _req("PATCH", f"issues/{number}", {"state": "closed"})
