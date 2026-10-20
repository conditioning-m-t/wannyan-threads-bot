#!/usr/bin/env bash
# 約 LOOP_MINUTES 分のあいだ、2分おきに「時刻になった投稿」と「新しいコメントへの返信」を処理する。
# GitHub の定期実行は混雑時に30分以上遅れることがあるため、1回の実行の中でくり返して取りこぼしを防ぐ。
set -u
cd "$(dirname "$0")"
end=$((SECONDS + ${LOOP_MINUTES:-27} * 60))
claude_ready=0

save_records() {
  ( cd .. &&
    # 置き場所の移行中でも記録を取りこぼさないよう、今の場所と accounts/ の両方を保存する
    for d in data "accounts/${ACCOUNT:-wannyan}/data"; do
      for f in replied.json escalations.json reply_log.txt manual_replies.json; do
        [ -f "$d/$f" ] && git add "$d/$f"
      done
    done
    if ! git diff --cached --quiet; then
      git commit -q -m "コメント返信の記録を更新" && git pull -q --rebase origin main && git push -q
    fi ) || echo "記録の保存に失敗（次回に再試行）"
}

while :; do
  echo "--- $(TZ=Asia/Tokyo date '+%H:%M')"
  # チャットで確認した返信や下書きの修正を取り込むため、毎回最新にする
  ( cd .. && git pull -q --rebase origin main ) || echo "最新の取り込みに失敗（そのまま続行）"
  DRY_RUN=0 python post_scheduled.py || echo "投稿処理でエラー"

  out=$(mktemp)
  REPLY_CHECK=1 GITHUB_OUTPUT="$out" python auto_reply.py || true
  pending=$(sed -n 's/^pending=//p' "$out"); rm -f "$out"
  if [ "${pending:-0}" -gt 0 ]; then
    if [ $claude_ready -eq 0 ]; then
      npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 && claude_ready=1
    fi
    REPLY_TEST=0 python auto_reply.py || echo "返信処理でエラー"
    save_records
  fi

  [ $SECONDS -ge $end ] && break
  sleep 120
done
