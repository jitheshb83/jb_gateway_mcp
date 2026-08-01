# jb_gateway_mcp

A local MCP server that acts as a credential-holding gateway to Google APIs
(Gmail, Calendar, Drive) and, via Enable Banking, read-only bank account data
(DNB, Nordea, Revolut, ...). AI agents call MCP tools; the server holds every
credential and decides — via a deny-by-default policy — what each caller is
allowed to do. Agents never see a token, password, API key, or raw account
number.

Full design/architecture: [DESIGN.md](DESIGN.md) / [DESIGN.pdf](DESIGN.pdf).

## Setup skills (recommended if you're using Claude Code)

Everything from "Install" onward can be driven interactively instead of by
hand — two skills ship in `.claude/skills/`:

- **`connect-google-account`** — connects or refreshes a Google account
  (Gmail/Calendar/Drive). Just ask, e.g. "connect my Google account to
  jb_gateway_mcp" or "refresh my Google credentials."
- **`connect-bank-account`** — connects or refreshes a bank account (DNB,
  Nordea, Revolut, or any other Enable Banking-supported institution). Just
  ask, e.g. "connect my DNB account" or "refresh my bank credentials."

Both walk through the steps documented below — app/consent registration
where a browser is unavoidable, running the onboarding CLI, adding the right
`policy.yaml` grants — and verify the result against live data before
calling it done. The rest of this README is the manual reference for each
step: useful if you're not driving this through Claude Code, or want to
understand exactly what the skills automate.

## Prerequisites

- Python 3.13 (managed automatically by `uv`)
- [`uv`](https://docs.astral.sh/uv/)
- For Google tools: a Google account you're willing to grant read-only (or
  send/write) API access to, and a Google Cloud project to create OAuth
  credentials in
- For bank tools: a free [Enable Banking](https://enablebanking.com/)
  account and the bank(s) you want to connect (DNB, Nordea, Revolut, ...
  currently — see §7)

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
uv run pytest -q      # 115 tests: unit + a real stdio round-trip test
uv run ruff check .
uv run mypy .
```

The stdio round-trip test in `tests/test_server.py` spawns the real server
process and calls `ping` over a real MCP session — the same mechanism any
client uses.

For a fuller live check (handshake, all 8 tools discovered, `ping`, policy
enforcement on the Google tools, and an audit-log integrity check), run the
project skill's smoke test:

```bash
uv run python .claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py
```

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

## 7. Connect a bank account (DNB, Nordea, Revolut, ...)

Independent of the Google setup above and §6 — do this before, after, or
without ever doing them; it's a separate provider with its own app
registration and onboarding CLI. `bank.*` tools are backed by **Enable
Banking**, a licensed AISP aggregator (direct bank PSD2 APIs require being a
regulated TPP with an eIDAS certificate — not viable for a personal
project).

### 7a. Register an Enable Banking application (one-time, in their Control Panel)

1. Sign in at [enablebanking.com/sign-in/](https://enablebanking.com/sign-in/)
   (email + magic link — no business registration needed).
2. Control Panel → **API applications** → **Add a new application**.
   - Name: anything identifiable.
   - Redirect URL: exactly `https://localhost:8080/callback` — Enable
     Banking requires `https://`, with no plain-http localhost exception
     (unlike Google).
   - Privacy/Terms URL: required fields, but **not validated** while the
     app stays in Restricted mode (own-accounts-only, which is what this
     project uses) — any placeholder URL works.
   - Let the browser generate the private key rather than supplying your
     own — it downloads once as `<application-id>.pem` and never leaves
     your machine.
3. **Keep the `.pem` out of the repo** — e.g.
   `~/.secrets/jb_gateway_mcp/enablebanking/<application-id>.pem`, same
   convention as `client_secret.json`.
4. **Activate the application.** A freshly registered app starts
   **"Inactive"** and returns `403 Forbidden` on every API call until you
   click **"Activate by linking accounts"** in the Control Panel and
   complete one bank login through their hosted UI. Do this **once per
   institution** you plan to connect (DNB, Nordea, Revolut, ...) — Restricted
   mode only ever serves accounts that have gone through this linking step.

### 7b. Onboard each institution

```bash
uv run onboard-bank --institution dnb \
  --application-id <uuid> \
  --private-key ~/.secrets/jb_gateway_mcp/enablebanking/<uuid>.pem
```

`--application-id`/`--private-key` are only needed the first time — every
institution after that reuses the stored app credential:

```bash
uv run onboard-bank --institution nordea
uv run onboard-bank --institution revolut
```

This is interactive: it opens a bank login URL in your browser, and after
you complete BankID/SCA login, the browser **fails to load** the final
redirect page (`https://localhost:8080/callback?...`) — that's expected,
nothing is listening there. Copy the full URL from the address bar and
paste it back at the terminal prompt; the CLI extracts the authorization
code from it. On success it prints e.g. `dnb onboarded: 1 account(s)
linked, consent valid until 2026-10-30` — never a secret value.

Consent is SCA-backed and valid for **90 days**; re-run the same command for
the same institution to refresh it — there's no separate "refresh" command,
and no way to extend a session without a fresh login (PSD2 requires it).

Supported institution aliases (see
[`src/jb_gateway_mcp/cli/onboard_bank.py`](src/jb_gateway_mcp/cli/onboard_bank.py)):
`dnb`, `nordea`, `revolut` — all currently Norway (`NO`). Adding a new one is
a two-line code change.

### 7c. Grant policy access

```yaml
callers:
  local:
    allow:
      - tool: bank.list_accounts
        scope: bank.readonly
      - tool: bank.get_balance
        scope: bank.readonly
      - tool: bank.summarize_spending
        scope: bank.readonly
      - tool: bank.list_transactions_summary
        scope: bank.readonly
      # Adds counterparty name + payment description to transaction results
      # (IBANs stay masked either way). Off by default:
      # - tool: bank.list_transactions_detailed
      #   scope: bank.transactions.detailed
```

Tiered by design: the default read-only tools never return counterparty
names, payment descriptions, or raw IBANs (every IBAN — the account
holder's own, and any counterparty's — is masked to its last 4 digits).
`bank.list_transactions_detailed` is the only tool that adds
counterparty/description text, and it needs its own explicit grant.

### 7d. Verify

```bash
uv run python .claude/skills/connect-bank-account/scripts/check_bank_status.py --live
```

Reports connection status (or "not connected"/"EXPIRED") and a live balance
check for every onboarded institution.

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
| `bank.list_accounts` | `bank.readonly` | `institution` — masked IBAN only |
| `bank.get_balance` | `bank.readonly` | `institution`, `account_uid` |
| `bank.summarize_spending` | `bank.readonly` | `institution`, `account_uid`, `date_from`, `date_to` — aggregated totals only, no line items |
| `bank.list_transactions_summary` | `bank.readonly` | `institution`, `account_uid`, `date_from`, `date_to` — date/amount/currency only |
| `bank.list_transactions_detailed` | `bank.transactions.detailed` | adds counterparty name/description (IBANs still masked) — not granted by default |

## Network & ports

**The gateway itself listens on nothing.** It's a stdio MCP server — the
client (Claude Desktop/Code, etc.) launches it as a subprocess and talks to
it over the process's stdin/stdout pipes. There's no port, no host, no URL,
no listening socket at any point during normal operation — it isn't
reachable over the network at all, by design (see
[DESIGN.md](DESIGN.md#locked-decisions)).

The one exception is the **one-time `onboard-google` step**: it briefly
starts a local HTTP server on `localhost:8080` (via
`google_auth_oauthlib`'s `InstalledAppFlow.run_local_server`) purely to
catch Google's OAuth redirect after you approve consent in the browser. It
shuts down immediately once the redirect arrives — nothing is listening
before or after that single command runs. If port 8080 is already in use on
your machine, that command will fail; there's currently no flag to change
the port, so free up 8080 or temporarily stop whatever else is using it
before running `onboard-google`.

## Troubleshooting

- **"no grant for caller X on tool Y"** — expected deny-by-default behavior.
  Add the grant to `policy.yaml` under the caller id you're using.
- **Re-consent error mentioning a revoked/expired refresh token** — re-run
  `onboard-google` for that account.
- **`403 Forbidden` from `onboard-bank`** — the Enable Banking application
  (or that specific institution) hasn't been through **"Activate by linking
  accounts"** in their Control Panel yet — see §7a step 4.
- **`multiple ASPSPs matched institution=...`** from `onboard-bank` — the
  institution name is genuinely ambiguous in that country (e.g. "DNB" vs.
  "DNB Corporate Mastercard"); narrow `_INSTITUTION_NAME_HINT` in
  `src/jb_gateway_mcp/cli/onboard_bank.py` for that alias and retry.
- **`NeedsReconsentError` / "consent ... expired" from a bank tool call** —
  the 90-day bank consent lapsed; re-run `onboard-bank --institution
  <alias>`.
- **Audit log** — every call (allowed, denied, or errored) is recorded at
  `JB_GATEWAY_AUDIT_LOG`. Tokens/secrets are redacted before writing.

## Security notes

- Never commit `client_secret.json`, any Enable Banking `.pem` private key,
  or any file matching `*credentials*.json` — `.gitignore` blocks these as a
  backstop, but treat it as a backstop, not a guarantee.
- Tokens and bank private keys live only in the OS keychain; they're never
  logged, never returned in a tool response, and never appear in an audit
  log entry — the audit log only ever records tool call *parameters*, never
  results.
- `gmail.send_message` and `calendar.create_event` are the only
  write-capable Google tools; they are not granted in the default
  `policy.yaml` — add them deliberately, only for callers that actually
  need them.
- Bank tools are architecturally read-only — the adapter's HTTP helper only
  ever issues GET requests; there is no code path capable of initiating a
  payment, even though Enable Banking's API separately supports one. Every
  IBAN (the account holder's own, and any transaction counterparty's) is
  masked to its last 4 digits before it leaves the adapter.
  `bank.list_transactions_detailed` is the only tool that surfaces
  counterparty names/payment descriptions, and it requires its own,
  off-by-default `policy.yaml` grant — the default tool set never sends
  that level of financial detail into an agent's context.

## Uninstalling

Deleting the repo folder alone is **not enough** — stored tokens and the
Google-side consent grant live outside it. Full teardown, in order:

1. **Remove it from every client you connected it to:**
   - Claude Desktop — delete the `jb-gateway-mcp` entry from
     `claude_desktop_config.json`, then restart Claude Desktop.
   - Claude Code — remove/delete `.mcp.json` (project-scoped), or
     `claude mcp remove jb-gateway-mcp` if you registered it globally
     instead.
   - Any other client — remove its equivalent `mcpServers` entry.

2. **Run the uninstall command** — revokes the account's grant on Google's
   side (RFC 7009 token revocation) *and* deletes its token from the OS
   keychain, in one step:
   ```bash
   uv run uninstall-google --account you@example.com
   ```
   Prompts for confirmation per account (add `--yes` to skip); repeatable
   with multiple `--account` flags to clean up more than one at once. If
   the network call to Google fails, it still deletes the local keychain
   entry and tells you to revoke access manually at
   [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
   — `--keep-remote-grant` skips the network call entirely and only deletes
   locally (e.g. if you already revoked access on Google's side, or the
   grant was for a different app).

   Deleting the repo without running this leaves the token sitting in your
   keychain, and the grant active on Google's side, indefinitely.

3. **Delete local state you don't want lingering** (all outside the repo,
   so `rm -rf`-ing the project directory won't touch these):
   - Audit log: `JB_GATEWAY_AUDIT_LOG` (default `~/.jb_gateway_mcp/`)
   - Your `client_secret.json` copy, wherever you stored it outside the repo

4. **Remove the project itself:**
   ```bash
   rm -rf /path/to/jb_gateway_mcp   # deletes .venv and all repo files together
   ```

Steps 1–4 are the parts people usually forget — the repo directory is the
least sensitive thing to clean up here.

### Uninstalling bank access

There's no `uninstall-bank` command yet (unlike `uninstall-google`) — bank
access is currently removed in two manual steps instead of one:

1. **Revoke on Enable Banking's side** — in their Control Panel, revoke the
   linked account or delete the application entirely. This is the step that
   actually matters for security; it's the equivalent of
   myaccount.google.com/permissions for banks.
2. **Delete the local keychain entries** — `keyring` stores these under the
   OS's native secret store (Keychain on macOS, Credential Manager on
   Windows, Secret Service on Linux), under service names
   `jb_gateway_mcp:enablebanking_app` (the app credential, one entry) and
   `jb_gateway_mcp:enablebanking_session` (one entry per institution alias
   you onboarded, e.g. `dnb`/`nordea`/`revolut`). Search for
   `jb_gateway_mcp:enablebanking` in your OS's credential manager UI (e.g.
   Keychain Access.app on macOS) and remove them, or delete a specific
   institution's private key file if you also want that gone
   (`~/.secrets/jb_gateway_mcp/enablebanking/`).
