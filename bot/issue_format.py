"""投稿案Issueの本文を作る／読み取る。

本文の形式（人がGitHubアプリで編集しても壊れにくいことを優先）:

    <!-- wannyan-drafts date=2026-10-20 -->
    ...説明...
    ### ① 07:00｜参加型
    - [ ] 07:00 を承認する
    <!-- post 07:00 -->
    ```text
    本文
    ```
    <!-- reply 07:00 -->        ← ツリー2投稿目がある場合だけ
    ```text
    返信本文（Amazonリンクなど）
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

WEEKDAYS = "月火水木金土日"
NUMBERS = "①②③④⑤"
LABEL = "投稿案"

HEADER_RE = re.compile(r"<!-- wannyan-drafts date=(\d{4}-\d{2}-\d{2}) -->")
CHECK_RE = re.compile(r"^- \[([ xX])\] (\d{2}:\d{2}) を承認する(.*)$", re.MULTILINE)
TOPIC_RE = re.compile(r"<!-- topic (\d{2}:\d{2}) (.+?) -->")
BLOCK_RE = re.compile(
    r"<!-- (post|reply) (\d{2}:\d{2}) -->\s*\n```text\n(.*?)\n```", re.DOTALL
)


@dataclass
class Draft:
    slot: str
    text: str
    reply: str | None = None
    approved: bool = False
    status: str = ""  # "", "posted", "skipped", "error"
    kind: str = ""
    memo: str = ""
    topic: str = ""  # Threadsのトピック（1投稿に1つ）


@dataclass
class DraftIssue:
    date: str
    drafts: list[Draft] = field(default_factory=list)


def render(date_str: str, posts: list[dict], approved: bool = True) -> tuple[str, str]:
    """drafts JSON から (タイトル, 本文) を作る。

    運用は「止めたい時だけ言う」方式なので、既定では承認済み（チェック済み）で作る。
    """
    d = date.fromisoformat(date_str)
    title = f"【投稿案】{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）"
    lines = [
        f"<!-- wannyan-drafts date={date_str} -->",
        f"**{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）の投稿案です。**",
        "",
        "チェックが入っている案は、その時刻に自動で投稿されます。止めたい案はチェックを外してください（ふだんはClaudeとのチャットで「2番やめて」と伝えればOK）。",
        "",
        "- 本文はこの画面の編集（右上の「…」→ Edit）で直接書き換えてOKです",
        "- `<!-- -->` の行と ```text の行は消さないでください",
        "",
    ]
    for i, p in enumerate(posts):
        num = NUMBERS[i] if i < len(NUMBERS) else f"{i + 1}."
        kind = p.get("type", "")
        lines += ["---", f"### {num} {p['slot']}｜{kind}".rstrip("｜"), ""]
        if p.get("memo"):
            lines += [f"> 狙い：{p['memo']}", ""]
        lines += [f"- [{'x' if approved else ' '}] {p['slot']} を承認する", ""]
        if p.get("topic"):
            lines += [f"<!-- topic {p['slot']} {p['topic'].strip()} -->", f"トピック：{p['topic'].strip()}", ""]
        lines += [f"<!-- post {p['slot']} -->", "```text", p["text"].strip(), "```", ""]
        if p.get("reply"):
            lines += [
                "ツリー2投稿目（自分の投稿への返信として続けて投稿されます）",
                "",
                f"<!-- reply {p['slot']} -->",
                "```text",
                p["reply"].strip(),
                "```",
                "",
            ]
    return title, "\n".join(lines)


def parse(body: str) -> DraftIssue | None:
    body = body.replace("\r\n", "\n")
    m = HEADER_RE.search(body)
    if not m:
        return None
    issue = DraftIssue(date=m.group(1))
    by_slot: dict[str, Draft] = {}
    for kind, slot, text in BLOCK_RE.findall(body):
        d = by_slot.setdefault(slot, Draft(slot=slot, text=""))
        if kind == "post":
            d.text = text.strip()
        else:
            d.reply = text.strip() or None
    for slot, topic in TOPIC_RE.findall(body):
        if slot in by_slot:
            by_slot[slot].topic = topic.strip()
    for mark, slot, rest in CHECK_RE.findall(body):
        if slot not in by_slot:
            continue
        d = by_slot[slot]
        d.approved = mark.lower() == "x"
        if "投稿済み" in rest:
            d.status = "posted"
        elif "見送り" in rest:
            d.status = "skipped"
        elif "エラー" in rest:
            d.status = "error"
    issue.drafts = sorted((d for d in by_slot.values() if d.text), key=lambda d: d.slot)
    return issue


def mark(body: str, slot: str, note: str) -> str:
    """チェック行の末尾に（✅ 投稿済み）などの印を付ける。"""
    pattern = re.compile(rf"^(- \[[ xX]\] {re.escape(slot)} を承認する)(.*)$", re.MULTILINE)
    return pattern.sub(lambda m: f"{m.group(1)}（{note}）", body, count=1)
