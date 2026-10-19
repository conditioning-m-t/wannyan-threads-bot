"""Claude のセッションから gh CLI（REST API）で Issue を扱う共通処理。

Claude Code の環境では GitHub GraphQL が使えないため、`gh api`（REST）だけを使う。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import quote

from issue_format import LABEL, parse


def repo_slug() -> str:
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    ).stdout.strip()
    slug = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
    return "/".join(slug.split("/")[-2:])


def gh_api(path: str, method: str = "GET", payload: dict | None = None, ok_codes=()) -> object:
    cmd = ["gh", "api", "-X", method, f"repos/{repo_slug()}/{path}"]
    stdin = None
    if payload is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(payload)
    res = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if res.returncode != 0:
        if any(str(c) in res.stdout + res.stderr for c in ok_codes):
            return None
        raise RuntimeError(f"gh api {method} {path} に失敗：{res.stderr.strip() or res.stdout.strip()}")
    return json.loads(res.stdout) if res.stdout.strip() else None


def open_draft_issues() -> list[dict]:
    return gh_api(f"issues?state=open&labels={quote(LABEL)}&per_page=50") or []


def find_issue(date_str: str) -> dict | None:
    for issue in open_draft_issues():
        parsed = parse(issue.get("body") or "")
        if parsed and parsed.date == date_str:
            return issue
    return None
