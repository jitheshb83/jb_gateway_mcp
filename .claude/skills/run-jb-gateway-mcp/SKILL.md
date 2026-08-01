---
name: run-jb-gateway-mcp
description: Launches the jb_gateway_mcp stdio MCP server and drives it with a real MCP client session (handshake, tool discovery, ping, policy-gated tool calls, audit log check). Use when asked to run, start, launch, smoke-test, or verify the jb_gateway_mcp server actually works.
---

# Running jb_gateway_mcp

jb_gateway_mcp is a **stdio** MCP server — it has no port or health endpoint
to `curl`. "Running" it means launching it exactly as a real MCP client
would and driving a session against it, which is what
`scripts/smoke_test.py` in this skill directory does.

## Prerequisites

- `uv` installed and on `PATH`
- Run from the repo root: `/Users/jithesh/Documents/GitHub/jb_gateway_mcp`
- `policy.yaml` should have grants under caller `local` for a fully
  "allowed" smoke test (see `README.md` §4) — but the script is useful
  either way: a denial is a correct, expected outcome when nothing is
  granted, not a failure.

## Setup

Dependencies are managed by `uv` — there's no separate build step, `uv run`
resolves/syncs the environment on first use. To pre-sync explicitly:

```bash
cd /Users/jithesh/Documents/GitHub/jb_gateway_mcp
uv sync
```

## Run + verify (one command)

```bash
cd /Users/jithesh/Documents/GitHub/jb_gateway_mcp
uv run python .claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py
```

What it does:

1. Spawns the real server via `scripts/start.sh` — the same entrypoint
   every client config in this repo (`.mcp.json`, `config/*.example.json`)
   uses.
2. Opens a real MCP `ClientSession`, does the protocol handshake.
3. Lists tools and checks all 8 expected ones are present (`ping` + 7
   Google tools).
4. Calls `ping`, expects `pong`.
5. Calls `gmail.list_messages`, `calendar.list_events`, `drive.list_files`
   against a placeholder account, and reports ALLOWED/DENIED per tool
   (driven by `policy.yaml`, caller id `local`).
6. Prints the resulting audit log and fails the script if any token/secret
   material is found in it.
7. Exits 0 on success. The spawned process's lifecycle is fully owned by
   the `stdio_client` async context manager — it's cleanly terminated on
   exit, no manual `kill` required.

## Testing against a real Google account

The script uses a placeholder account (`smoke-test@example.com`), so the
Google API calls will fail/be denied regardless of policy — that's expected
and still exercises the full router → policy → adapter → audit path. To
test against real data, edit `ACCOUNT` at the top of
`scripts/smoke_test.py` to an already-onboarded real address (see
`README.md` §2–3) for a local one-off run — don't commit a real account
email into this shared script.

## Automated test suite (no spawned process needed for most of it)

```bash
uv run pytest -q      # unit tests + one real stdio round-trip test
uv run ruff check .
uv run mypy .
```

Verified state as of this run: 77 tests pass, ruff clean, mypy clean on 31
source files.

## Other binaries

This project ships two more entry points besides the server itself (see
`[project.scripts]` in `pyproject.toml`) — not part of "running" the
server, but part of the same unit:

| Binary | Purpose |
|---|---|
| `uv run onboard-google --account <email> --client-secrets <path>` | One-time, human-interactive OAuth consent flow for a Google account. Opens a browser, briefly binds `localhost:8080` for the redirect. See the `connect-google-account` skill (in the [jb_claude_pluggins](https://github.com/jitheshb83/jb_claude_pluggins) `jb-google-notify-plugin`) for the full guided flow (client-secrets setup, scope selection, policy.yaml grants). |
| `uv run uninstall-google --account <email>` | Revokes the account's grant on Google's side and deletes its keychain token. See `README.md` §"Uninstalling". |

## Gotchas

- **`warning: VIRTUAL_ENV=... does not match the project environment path
  .venv and will be ignored`** — appears on every `uv run` invocation in
  this environment because a pyenv-managed virtualenv is active in the
  shell. Harmless — `uv` correctly ignores it and uses the project's own
  `.venv`. Don't try to "fix" it by deactivating pyenv; it doesn't affect
  correctness.
- **The server prints nothing useful on its own.** It speaks JSON-RPC over
  stdout per the MCP protocol — running `./scripts/start.sh` directly in a
  terminal just blocks silently waiting for a client. That's expected, not
  a hang; use the smoke test driver instead of eyeballing raw output.
- **Google tool calls against an unonboarded account error, they don't
  hang or silently no-op** — `no credential stored for provider='google'
  account=...`. This is the router/policy/adapter path working correctly
  down to the credential-store lookup, not a bug in the smoke test.
- **`calendar.list_events` has no date-range filter** (no `timeMin`/
  `timeMax` param — see `src/jb_gateway_mcp/adapters/google_calendar.py`).
  It calls the Google API with `singleEvents=True, orderBy="startTime"`
  and no lower bound, so results start from the *earliest event on the
  calendar ever*, not "upcoming from now." For a "this month" or "upcoming"
  summary, fetch a large `max_results` and filter client-side by date —
  don't assume the results are already scoped to the present.
- **`drive.read_file` returns `content: null` for binary files** (PDFs,
  images, etc.) — by design (see `_fetch_content` in
  `src/jb_gateway_mcp/adapters/google_drive.py`), it only fetches text for
  Google-native docs (exported) or `text/*`/`application/json` MIME types.
  There is no way to fetch raw file bytes through this gateway — for a PDF
  the only options are the file's `webViewLink`/Drive URL for the user to
  open manually, or extending the adapter.

## Troubleshooting

- **`error: 'uv' is not installed or not on PATH`** (from
  `scripts/start.sh`) — install `uv` (https://docs.astral.sh/uv/).
- **`error: policy.yaml not found in <root>`** (from `scripts/start.sh`) —
  run from the repo root, or set `JB_GATEWAY_POLICY_FILE` to an absolute
  path.
- **Smoke test reports `MISSING expected tools`** — the server started but
  a tool registration changed; check `src/jb_gateway_mcp/adapters/` against
  the `expected` set in `scripts/smoke_test.py`.
- **`no grant for caller 'local' on tool ...`** — expected deny-by-default
  behavior; add the grant under `callers: local: allow:` in `policy.yaml`
  (see `README.md` §4).
- **If none of the above fixes it, do not fall back to another tool for
  the same data** — e.g. this environment may also expose native
  `claude_ai_Google_*` (`Gmail`/`Google Calendar`/`Google Drive`)
  connectors. Those bypass `policy.yaml` and the audit log entirely, so
  using one as a substitute defeats the point of this gateway and may
  answer from the wrong Google account. Stop and tell the user what's
  broken instead.
