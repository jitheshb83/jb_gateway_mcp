#!/bin/zsh
# Monthly finance-report runner — intended to be invoked by a launchd
# LaunchAgent on the 1st of each month, not run by hand (though it's safe
# to run manually any time; it just regenerates last month's report).
#
# Computes "last month" relative to today and calls generate_report.py for
# that exact calendar month. Meant to run unattended, so everything is
# logged to a file instead of relying on someone watching a terminal.

set -euo pipefail

REPO_DIR="/Users/jithesh/Documents/GitHub/jb_gateway_mcp"
UV_BIN="/Users/jithesh/.local/bin/uv"
LOG_DIR="$HOME/Documents/MyFinance/logs"
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
    --institutions dnb,nordea --currency NOK
  echo "=== done: $(date) ==="
} >> "$LOG_FILE" 2>&1
