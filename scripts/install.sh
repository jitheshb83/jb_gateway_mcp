#!/usr/bin/env bash
# Interactive installer for jb_gateway_mcp — walks a new user through the
# steps in README.md (`uv sync`, Google account onboarding, bank account
# onboarding, and a final smoke test) instead of copy-pasting each command
# by hand. Safe to re-run; every step is optional and skippable.
#
# Deliberately does NOT touch policy.yaml. Deciding which tools a caller can
# use is a security decision for a human to make by reading the grant they're
# adding (see policy.yaml's own header comment) — this script only tells you
# exactly what to add and where, it never writes grants for you.
#
# Run from anywhere; resolves the project root itself:
#   ./scripts/install.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

_INSTITUTIONS="dnb nordea revolut"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    \033[33mwarning: %s\033[0m\n' "$1" >&2; }
err() { printf 'error: %s\n' "$1" >&2; }

confirm() {
  # confirm "question" [default: y|n]  -> 0 if yes, 1 if no
  local prompt="$1" default="${2:-n}" reply hint
  if [ "$default" = "y" ]; then hint="Y/n"; else hint="y/N"; fi
  read -r -p "    $prompt [$hint]: " reply || reply=""
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]]
}

ask() {
  # ask "prompt" default_var_name -> echoes the answer (or default if blank)
  local prompt="$1" default="${2:-}" reply
  if [ -n "$default" ]; then
    read -r -p "    $prompt [$default]: " reply || reply=""
    echo "${reply:-$default}"
  else
    read -r -p "    $prompt: " reply || reply=""
    echo "$reply"
  fi
}

# Local, read-only checks against the OS keychain — no network calls, no
# writes. Used so re-running this script doesn't blindly force a fresh
# browser/consent flow for an account that's already connected.

google_connected() {
  # google_connected <account> -> exit 0 if a token is already stored
  uv run python -c "
import sys
from jb_gateway_mcp.credentials import CredentialStore, CredentialNotFoundError
try:
    CredentialStore().get_token('google', sys.argv[1])
except CredentialNotFoundError:
    sys.exit(1)
" "$1" 2>/dev/null
}

bank_status() {
  # bank_status <institution> -> prints "connected <iso-date>" | "expired <iso-date>" | "none"
  uv run python -c "
import sys
from jb_gateway_mcp.credentials_bank import BankCredentialStore, BankCredentialNotFoundError, NeedsReconsentError
store = BankCredentialStore()
try:
    session = store.get_valid_session(sys.argv[1])
    print(f'connected {session.valid_until.isoformat()}')
except NeedsReconsentError:
    session = store.get_session(sys.argv[1])
    print(f'expired {session.valid_until.isoformat()}')
except BankCredentialNotFoundError:
    print('none')
" "$1" 2>/dev/null
}

bold "jb_gateway_mcp interactive installer"
info "This wraps the manual steps in README.md — every step below is optional."
info "Ctrl-C at any point to stop; nothing here modifies policy.yaml."

# --- 1. Prerequisites -------------------------------------------------------
step "1. Checking prerequisites"

if ! command -v uv >/dev/null 2>&1; then
  err "'uv' is not installed or not on PATH — see https://docs.astral.sh/uv/"
  exit 1
fi
info "uv found: $(uv --version)"

# --- 2. Install dependencies -------------------------------------------------
step "2. Installing dependencies (uv sync)"
if ! uv sync; then
  err "'uv sync' failed — see output above."
  exit 1
fi
info "Dependencies installed."

if [ ! -f "$PROJECT_ROOT/policy.yaml" ]; then
  warn "no policy.yaml found at $PROJECT_ROOT/policy.yaml"
  if confirm "Create a safe, deny-everything policy.yaml now?" y; then
    printf 'callers: {}\n' > "$PROJECT_ROOT/policy.yaml"
    info "Wrote a deny-everything policy.yaml. See README.md \"Grant policy access\" to add grants."
  else
    warn "the server will refuse to start (even for 'ping') without a policy.yaml — see README.md."
  fi
else
  info "policy.yaml already present."
fi

# --- 3. Google account (optional) -------------------------------------------
step "3. Google account (Gmail / Calendar / Drive) — optional"
if confirm "Onboard a Google account now?" n; then
  account="$(ask 'Google account email' '')"
  if [ -z "$account" ]; then
    warn "no account given, skipping Google onboarding."
  else
    do_google=true
    if google_connected "$account"; then
      info "$account already has a Google token stored in this machine's keychain."
      confirm "Re-run onboarding for it anyway (e.g. revoked token, add more scopes)?" n || do_google=false
    fi

    if [ "$do_google" = true ]; then
      info "You need a client_secret.json from Google Cloud Console first — see README.md \"Connect a Google account\" §2a if you don't have one yet."
      if confirm "Do you already have a client_secret.json ready?" n; then
        secrets_path=""
        while true; do
          secrets_path="$(ask 'Path to client_secret.json' '')"
          [ -f "$secrets_path" ] && break
          warn "file not found: $secrets_path"
          confirm "Try another path?" y || { secrets_path=""; break; }
        done
        if [ -n "$secrets_path" ]; then
          extra_scopes=()
          if confirm "Also grant send/write access (gmail.send + calendar write), not just read-only?" n; then
            extra_scopes=(--scopes \
              "https://www.googleapis.com/auth/gmail.readonly" \
              "https://www.googleapis.com/auth/gmail.send" \
              "https://www.googleapis.com/auth/calendar" \
              "https://www.googleapis.com/auth/drive.readonly")
          fi
          info "Running onboard-google (opens a browser for consent)..."
          if uv run onboard-google --account "$account" --client-secrets "$secrets_path" "${extra_scopes[@]+"${extra_scopes[@]}"}"; then
            info "Google account onboarded. Remember to add matching grants to policy.yaml (README.md \"Grant policy access\")."
          else
            warn "onboard-google failed — see output above."
          fi
        fi
      else
        info "Skipping — see README.md \"Connect a Google account\" §2a, then re-run this script."
      fi
    else
      info "Leaving the existing connection for $account in place."
    fi
  fi
else
  info "Skipped."
fi

# --- 4. Bank account (optional) ---------------------------------------------
step "4. Bank account (DNB / Nordea / Revolut via Enable Banking) — optional"
if confirm "Onboard a bank account now?" n; then
  info "Supported institutions: $_INSTITUTIONS"
  info "First institution ever onboarded needs an Enable Banking application-id + private-key .pem — see README.md \"Connect a bank account\" §6a."
  onboard_another=true
  while [ "$onboard_another" = true ]; do
    institution=""
    while true; do
      institution="$(ask "Institution ($_INSTITUTIONS)" '')"
      case " $_INSTITUTIONS " in
        *" $institution "*) break ;;
        *) warn "unknown institution '$institution' — must be one of: $_INSTITUTIONS" ;;
      esac
    done

    do_bank=true
    status="$(bank_status "$institution")"
    case "$status" in
      "connected "*)
        info "$institution is already connected (consent valid until ${status#connected })."
        confirm "Re-run consent for it anyway (e.g. link another account at this bank)?" n || do_bank=false
        ;;
      "expired "*)
        info "$institution's consent expired at ${status#expired } — refreshing it now."
        ;;
      *) : ;; # not connected yet — proceed with a normal first-time/refresh flow
    esac

    if [ "$do_bank" = true ]; then
      app_args=()
      if confirm "Provide an application-id + private-key now (first-time setup)?" n; then
        app_id="$(ask 'Enable Banking application-id' '')"
        key_path=""
        while true; do
          key_path="$(ask 'Path to the application private key .pem' '')"
          [ -f "$key_path" ] && break
          warn "file not found: $key_path"
          confirm "Try another path?" y || { key_path=""; break; }
        done
        if [ -n "$app_id" ] && [ -n "$key_path" ]; then
          app_args=(--application-id "$app_id" --private-key "$key_path")
        fi
      fi

      info "Running onboard-bank --institution $institution (opens a browser for bank login)..."
      if uv run onboard-bank --institution "$institution" "${app_args[@]+"${app_args[@]}"}"; then
        info "$institution onboarded. Remember to add matching grants to policy.yaml (README.md \"Grant policy access\", §6c)."
      else
        warn "onboard-bank failed for $institution — see output above."
      fi
    else
      info "Leaving the existing connection for $institution in place."
    fi

    confirm "Onboard another institution?" n && onboard_another=true || onboard_another=false
  done
else
  info "Skipped."
fi

# --- 5. Smoke test -----------------------------------------------------------
step "5. Verify the install"
if confirm "Run the smoke test now (handshake, tool discovery, ping, policy check)?" y; then
  if [ -f "$PROJECT_ROOT/.claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py" ]; then
    uv run python .claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py || warn "smoke test reported a problem — see output above."
  else
    info "Smoke test script not found; running the unit/integration test suite instead."
    uv run pytest -q || warn "test suite reported a problem — see output above."
  fi
else
  info "Skipped — you can run it any time with:"
  info "  uv run python .claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py"
fi

# --- Done --------------------------------------------------------------------
step "Done"
info "Next steps:"
info "  - Add grants for whatever you onboarded above to policy.yaml (README.md \"Grant policy access\")."
info "  - Point an MCP client at this server (README.md \"Connect an MCP client\" §5) — Claude Code"
info "    already picks up the .mcp.json in this repo automatically."
