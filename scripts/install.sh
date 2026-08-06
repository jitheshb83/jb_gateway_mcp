#!/usr/bin/env bash
# One-shot standalone installer for jb_gateway_mcp.
#
# Installs the server itself and wires it into an MCP client — nothing
# about *credentials* (Google OAuth, Enable Banking) is handled here, by
# design: those are per-service, per-account steps you do deliberately,
# not something an install script should touch. See README.md steps 2-4
# (Google) and 7 (bank) for that, after this script finishes.
#
# What this does, in order:
#   1. Installs `uv` if it's not already on PATH (official astral.sh
#      installer — same one-liner README.md's Prerequisites section links
#      to).
#   2. `uv tool install`s jb-gateway-mcp from this repo, putting
#      jb-gateway-mcp / onboard-google / onboard-bank / uninstall-google on
#      PATH.
#   3. Creates ~/.jb_gateway_mcp/policy.yaml with the safe deny-everything
#      default (`callers: {}`) if it doesn't already exist — leaves it
#      alone if it does, so re-running this script is safe.
#   4. If the `claude` CLI is present, registers the server with Claude
#      Code (`claude mcp add`, user scope — available in every project,
#      not just one directory). Otherwise prints the manual step for
#      Claude Desktop / another client.
set -euo pipefail

REPO_URL="https://github.com/jitheshb83/jb_gateway_mcp.git"
POLICY_DIR="$HOME/.jb_gateway_mcp"
POLICY_FILE="$POLICY_DIR/policy.yaml"

echo "== jb_gateway_mcp installer =="

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "-- 'uv' not found, installing it (https://docs.astral.sh/uv/)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The official installer puts uv on PATH for new shells via shell rc
  # files, but this script's own PATH needs it right now too.
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv install finished but 'uv' still isn't on PATH — open a new terminal and re-run this script." >&2
    exit 1
  fi
fi

echo
echo "-- Installing jb-gateway-mcp (this puts jb-gateway-mcp, onboard-google, onboard-bank, uninstall-google on PATH)..."
uv tool install --python 3.13 "git+${REPO_URL}"

echo
if [ -f "$POLICY_FILE" ]; then
  echo "-- Policy file already exists, leaving it as-is: $POLICY_FILE"
else
  mkdir -p "$POLICY_DIR"
  echo 'callers: {}' > "$POLICY_FILE"
  echo "-- Created default policy file (denies every tool until you grant access): $POLICY_FILE"
fi

echo
if command -v claude >/dev/null 2>&1; then
  echo "-- Registering jb-gateway-mcp with Claude Code (user scope)..."
  claude mcp add jb-gateway-mcp --scope user -- jb-gateway-mcp
else
  echo "-- Claude Code CLI not found, skipping automatic MCP registration."
  echo "   For Claude Desktop or another client, see README.md \"Connect a real client\":"
  echo "   https://github.com/jitheshb83/jb_gateway_mcp#6-connect-a-real-client"
fi

echo
echo "== Done =="
echo "Next: connect credentials — README.md steps 2-4 for Google (Gmail/Calendar/Drive),"
echo "step 7 for bank accounts (DNB/Nordea/Revolut). Nothing works until you grant"
echo "policy access and onboard at least one account."
