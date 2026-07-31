# jb_gateway_mcp

A local MCP server that acts as a credential-holding gateway to Google APIs
(Gmail, Calendar, Drive). AI agents call MCP tools; the server holds every
OAuth token and decides — via a deny-by-default policy — what each caller is
allowed to do. Agents never see a token, password, or API key.

Full design/architecture: [DESIGN.md](DESIGN.md) / [DESIGN.pdf](DESIGN.pdf).

## Prerequisites

- Python 3.13 (managed automatically by `uv`)
- [`uv`](https://docs.astral.sh/uv/)
- A Google account you're willing to grant read-only (or send/write) API
  access to, and a Google Cloud project to create OAuth credentials in

## 1. Install

```bash
cd jb_gateway_mcp
uv sync
```

## 2. Create a Google OAuth client (one-time, in Google Cloud Console)

The gateway needs its own OAuth client to run the consent flow. You do this
once, in your own Google account — nothing here can do it for you:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and
   create (or pick) a project.
2. **APIs & Services → Library** — enable the **Gmail API**, **Google
   Calendar API**, and **Google Drive API**.
3. **APIs & Services → OAuth consent screen** — configure it (External is
   fine for personal use; add your own account as a test user if the app
   stays in "Testing" mode).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   — Application type: **Desktop app**. Download the resulting JSON — this
   is your `client_secret.json`.
5. **Keep this file out of the repo.** Store it somewhere outside the
   project (e.g. `~/.secrets/jb_gateway_mcp/client_secret.json`). The
   `.gitignore` here already blocks `client_secret*.json` as a backstop, but
   don't rely on that — don't put it in the repo directory at all.

## 3. Onboard a Google account

This is a one-time, human-run step per Google account. It opens a browser
for you to log in and grant consent; the resulting token is written to your
OS keychain — it never touches disk in plaintext and is never visible to any
agent.

```bash
uv run onboard-google \
  --account you@example.com \
  --client-secrets ~/.secrets/jb_gateway_mcp/client_secret.json
```

By default this requests **read-only** scopes (Gmail, Calendar, Drive). To
also allow sending mail or creating events, pass `--scopes` explicitly:

```bash
uv run onboard-google \
  --account you@example.com \
  --client-secrets ~/.secrets/jb_gateway_mcp/client_secret.json \
  --scopes \
    https://www.googleapis.com/auth/gmail.readonly \
    https://www.googleapis.com/auth/gmail.send \
    https://www.googleapis.com/auth/calendar \
    https://www.googleapis.com/auth/drive.readonly
```

On success it prints the account and granted scopes — never a token value.
Re-run this any time a refresh token is revoked (the server will raise a
clear re-consent error if that happens mid-use).

## 4. Grant policy access

The server ships with `policy.yaml` denying everything by default — no
caller can use any tool until you explicitly grant it. Edit `policy.yaml`:

```yaml
callers:
  local:
    allow:
      - tool: gmail.list_messages
        scope: gmail.readonly
      - tool: gmail.read_message
        scope: gmail.readonly
      - tool: calendar.list_events
        scope: calendar.readonly
      - tool: drive.list_files
        scope: drive.readonly
      - tool: drive.read_file
        scope: drive.readonly
      # Only add these if you actually want an agent to be able to send
      # mail / create events on your behalf:
      # - tool: gmail.send_message
      #   scope: gmail.send
      # - tool: calendar.create_event
      #   scope: calendar.events
```

`local` is the default caller identity for v1 (single-user, local stdio
deployment — see [DESIGN.md §7](DESIGN.md)). Override it with the
`JB_GATEWAY_CALLER_ID` environment variable if you want distinct policies
per launching client (see §6 below).

## 5. Run it standalone (quick manual test)

The server is started via [`scripts/start.sh`](scripts/start.sh) — a thin
wrapper that resolves the project root, checks `uv` and `policy.yaml` are
present, and `exec`s into `uv run jb-gateway-mcp` (so a launching client's
process management/signals reach the real server directly, no wrapper
process left in between). This is the same command every client config
below points at.

```bash
./scripts/start.sh
```

This blocks, speaking MCP over stdio — it's meant to be launched by a
client, not run interactively. To sanity-check it without a full client,
run the automated test suite instead:

```bash
uv run pytest -q      # 69 tests: unit + a real stdio round-trip test
uv run ruff check .
uv run mypy .
```

The stdio round-trip test in `tests/test_server.py` spawns the real server
process and calls `ping` over a real MCP session — the same mechanism any
client uses.

## 6. Connect a real client

Every client config below launches [`scripts/start.sh`](scripts/start.sh)
with `JB_GATEWAY_CALLER_ID=local` — the same caller id already granted
read-only Gmail/Calendar/Drive access in `policy.yaml` and verified working
end-to-end. This repo is a single-user, local deployment (see
[DESIGN.md §7](DESIGN.md)), so every client sharing one caller id is
intentional, not a shortcut — they all run as you, on your machine. If you
later want per-client policies (e.g. a stricter grant set for one client),
give it its own `JB_GATEWAY_CALLER_ID` and add a matching entry under
`callers:` in `policy.yaml` — until you do, any caller id with no entry
there is denied everything by default.

### Claude Desktop

Copy [`config/claude_desktop_config.example.json`](config/claude_desktop_config.example.json)
into your Claude Desktop config
(`~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS), replacing the placeholder path with this repo's absolute path, then
restart Claude Desktop.

### Claude Code

A ready-to-use [`.mcp.json`](.mcp.json) already exists at this repo's root
(project-scoped — Claude Code picks it up automatically when you open this
folder). If you'd rather register it globally instead, `claude mcp add` is
the CLI route — run `claude mcp --help` to confirm the exact current flags
for your installed version.

### Any other MCP client (Cursor, Windsurf, Cline, etc.)

Most MCP clients use the same `mcpServers` JSON shape. See
[`config/mcp_client_generic.example.json`](config/mcp_client_generic.example.json)
and that client's own docs for where its config file lives.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `JB_GATEWAY_CALLER_ID` | `local` | Identity used for every policy check and audit entry in this process. Must match a `callers:` key in `policy.yaml` to be granted anything. |
| `JB_GATEWAY_POLICY_FILE` | `policy.yaml` (relative to cwd) | Path to the policy file. |
| `JB_GATEWAY_AUDIT_LOG` | `~/.jb_gateway_mcp/audit.jsonl` | Path to the audit log (JSON Lines, one entry per tool call, secrets redacted). Parent directory is created automatically. |

## Tool catalog

| Tool | Scope | Notes |
|---|---|---|
| `ping` | — (ungated smoke-test tool) | Always available, not policy-gated |
| `gmail.list_messages` | `gmail.readonly` | `account`, `query` |
| `gmail.read_message` | `gmail.readonly` | `account`, `message_id` |
| `gmail.send_message` | `gmail.send` | `account`, `to`, `subject`, `body` — not granted by default |
| `calendar.list_events` | `calendar.readonly` | `account`, `calendar_id`, `max_results` |
| `calendar.create_event` | `calendar.events` | `account`, `calendar_id`, `summary`, `start_iso`, `end_iso` — not granted by default |
| `drive.list_files` | `drive.readonly` | `account`, `query`, `page_size` |
| `drive.read_file` | `drive.readonly` | `account`, `file_id` |

## Troubleshooting

- **"no grant for caller X on tool Y"** — expected deny-by-default behavior.
  Add the grant to `policy.yaml` under the caller id you're using.
- **Re-consent error mentioning a revoked/expired refresh token** — re-run
  `onboard-google` for that account.
- **Audit log** — every call (allowed, denied, or errored) is recorded at
  `JB_GATEWAY_AUDIT_LOG`. Tokens/secrets are redacted before writing.

## Security notes

- Never commit `client_secret.json` or any file matching `*credentials*.json`
  — `.gitignore` blocks these as a backstop, but treat it as a backstop, not
  a guarantee.
- Tokens live only in the OS keychain; they're never logged, never returned
  in a tool response, and never appear in an audit log entry.
- `gmail.send_message` and `calendar.create_event` are the only
  write-capable tools; they are not granted in the default `policy.yaml` —
  add them deliberately, only for callers that actually need them.
