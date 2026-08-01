#!/bin/zsh
# Monthly finance-report runner — intended to be invoked by a launchd
# LaunchAgent on the 1st of each month, not run by hand (though it's safe
# to run manually any time; it just regenerates last month's report).
#
# Computes "last month" relative to today, calls generate_report.py for
# that exact calendar month, then emails a short status notification
# (success with headline numbers, or failure with the reason) via
# notify_email.py. Meant to run unattended, so everything is also logged
# to a file regardless of whether the email succeeds.
#
# Deliberately NOT `set -e`: a failed generate_report.py run must still
# reach the failure-notification email below it, not abort the script.

set -uo pipefail

REPO_DIR="/Users/jithesh/Documents/GitHub/jb_gateway_mcp"
UV_BIN="/Users/jithesh/.local/bin/uv"
OUT_DIR="$HOME/Documents/MyFinance"
LOG_DIR="$OUT_DIR/logs"
CURRENCY="NOK"
INSTITUTIONS="dnb,nordea"
mkdir -p "$LOG_DIR"

# BSD date (macOS): first of this month, minus one day = last day of last
# month; first of that month = last month's start.
LAST_MONTH_END=$(date -v1d -v-1d +%Y-%m-%d)
LAST_MONTH_START=$(date -v1d -v-1d -v1d +%Y-%m-%d)
LABEL=$(date -v1d -v-1d +%Y-%m)

LOG_FILE="$LOG_DIR/${LABEL}-run-$(date +%Y%m%d-%H%M%S).log"

{
  echo "=== finance-report monthly run: $(date) ==="
  echo "Period: $LAST_MONTH_START .. $LAST_MONTH_END"
  cd "$REPO_DIR"

  "$UV_BIN" run python .claude/skills/finance-report/scripts/generate_report.py \
    --from "$LAST_MONTH_START" --to "$LAST_MONTH_END" \
    --institutions "$INSTITUTIONS" --currency "$CURRENCY"
  REPORT_EXIT=$?
  echo "generate_report.py exit: $REPORT_EXIT"

  INSTITUTIONS_SLUG=$(echo "$INSTITUTIONS" | tr ',' '-')
  REPORT_PATH="$OUT_DIR/reports/${LABEL}-${INSTITUTIONS_SLUG}-report.html"

  if [ "$REPORT_EXIT" -eq 0 ]; then
    "$UV_BIN" run python .claude/skills/finance-report/scripts/notify_email.py \
      --status success --label "$LABEL" --currency "$CURRENCY" \
      --out-dir "$OUT_DIR" --report-path "$REPORT_PATH"
  else
    "$UV_BIN" run python .claude/skills/finance-report/scripts/notify_email.py \
      --status failure --label "$LABEL" --currency "$CURRENCY" \
      --out-dir "$OUT_DIR" --log-path "$LOG_FILE" \
      --detail "generate_report.py exited $REPORT_EXIT — see log for the actual error"
  fi

  echo "=== done: $(date) ==="
} >> "$LOG_FILE" 2>&1

# Report generation's own exit code is what launchd should see as this
# job's result — the notification step succeeding or failing shouldn't
# mask (or fake) that signal either way.
exit "$REPORT_EXIT"
