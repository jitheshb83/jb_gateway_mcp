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
