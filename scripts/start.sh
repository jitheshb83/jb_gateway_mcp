#!/usr/bin/env bash
# Starts the jb_gateway_mcp server over stdio.
#
# Intended to be launched BY an MCP client (Claude Desktop, Claude Code, or
# any other MCP-compatible client) — not run interactively. It speaks
# JSON-RPC on stdout, so nothing in this script (or anything it execs) may
# print to stdout; diagnostics below go to stderr.
#
# Caller identity, policy file, and audit log path are all controlled by the
# launching client via env vars (JB_GATEWAY_CALLER_ID, JB_GATEWAY_POLICY_FILE,
# JB_GATEWAY_AUDIT_LOG) — see README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is not installed or not on PATH — see https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [ ! -f "$PROJECT_ROOT/policy.yaml" ]; then
  echo "error: policy.yaml not found in $PROJECT_ROOT" >&2
  exit 1
fi

# exec (not a plain call) so this script's PID is replaced by uv's — the
# launching client's process-lifecycle management (start/stop/signals)
# reaches the real server directly, with no wrapper process in between.
exec uv run jb-gateway-mcp
