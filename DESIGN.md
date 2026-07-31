# jb_gateway_mcp — Design

An MCP server that acts as a credential-holding gateway to external APIs. AI
agents/workers call MCP tools; the server holds all secrets (OAuth tokens,
API keys) and decides what's allowed. Agents never see, request, or handle
credentials.

## Goals / non-goals

**Goals**
- Agents authenticate to *this server* only (implicitly, via being an
  allowed local MCP client) — never to Google, banks, etc. directly.
- Every external call is mediated by a deny-by-default policy check.
- Every external call is audited (who/what/when), with secrets redacted.
- Adding a new provider is a new adapter module, not a core rewrite.

**Non-goals (v1)**
- No networked/multi-host transport (stdio only for now).
- No write/transfer capability for financial services — read-only or not
  integrated at all.
- No runtime human-approval step — authorization is static policy only.

## Locked decisions

| Area | Decision |
|---|---|
| Transport | Local stdio; core kept transport-agnostic |
| MVP scope | Google APIs (Gmail, Calendar, Drive) |
| Financial services | Later phase, read-only only |
| Credential storage | OS keychain via `keyring` |
| Authorization | Static policy file, deny-by-default, no runtime approval |

---

## Architecture

```mermaid
graph TB
    subgraph Client["Agent / Client"]
        A[AI Agent or Worker<br/>Claude Desktop / Claude Code / custom]
    end

    subgraph Server["MCP Gateway Server (stdio process)"]
        R[Tool Router]
        P[Policy Engine<br/>policy.yaml]
        AU[Audit Logger<br/>secrets redacted]
        CS[Credential Store<br/>keyring-backed]
        TL[Token Lifecycle<br/>auto-refresh]

        subgraph Adapters["Service Adapters"]
            GM[Gmail Adapter]
            GC[Calendar Adapter]
            GD[Drive Adapter]
        end
    end

    subgraph Human["Human (out-of-band)"]
        CLI[Onboarding CLI<br/>one-time OAuth consent]
    end

    K[(OS Keychain)]
    GAPI[Google APIs]

    A -->|MCP tool call, stdio| R
    R -->|is caller+tool+scope allowed?| P
    P -->|allow| R
    P -->|deny| R
    R --> Adapters
    GM & GC & GD -->|fetch live token| CS
    CS <--> K
    CS --> TL
    TL -->|refresh if expired| GAPI
    GM & GC & GD -->|API call with token| GAPI
    R --> AU
    CLI -->|seed tokens once| CS

    style P fill:#7c3aed,color:#fff
    style CS fill:#059669,color:#fff
    style AU fill:#d97706,color:#fff
```

**Key property:** tokens flow only between `Credential Store`, `OS Keychain`,
`Token Lifecycle`, and the `Adapters` internally. Nothing in that loop ever
appears in a tool response, a log line, or crosses back to the `Agent`.

---

## Flow 1 — Tool call (steady state, authorized)

```mermaid
sequenceDiagram
    participant Agent
    participant Router as Tool Router
    participant Policy as Policy Engine
    participant Adapter as Gmail Adapter
    participant Creds as Credential Store
    participant Keychain as OS Keychain
    participant Google as Google API
    participant Audit as Audit Logger

    Agent->>Router: call tool "gmail.list_messages"(query)
    Router->>Policy: is caller "agent-x" allowed<br/>tool "gmail.list_messages"?
    Policy-->>Router: allow (scope: gmail.readonly)
    Router->>Adapter: invoke(query)
    Adapter->>Creds: get_token(account="me@x.com", provider="google")
    Creds->>Keychain: read secret
    Keychain-->>Creds: token (not expired)
    Creds-->>Adapter: access_token
    Adapter->>Google: GET /gmail/v1/messages (Bearer token)
    Google-->>Adapter: message list
    Adapter-->>Router: result (no token attached)
    Router->>Audit: log(caller, tool, params, outcome=success)
    Router-->>Agent: result
```

## Flow 2 — Tool call denied by policy

```mermaid
sequenceDiagram
    participant Agent
    participant Router as Tool Router
    participant Policy as Policy Engine
    participant Audit as Audit Logger

    Agent->>Router: call tool "gmail.send_message"(...)
    Router->>Policy: is caller "agent-x" allowed<br/>tool "gmail.send_message"?
    Policy-->>Router: deny (not in policy.yaml for agent-x)
    Router->>Audit: log(caller, tool, outcome=denied)
    Router-->>Agent: error: "tool not permitted for this caller"
```

No adapter is ever invoked on a deny — the credential store is never touched.

## Flow 3 — OAuth onboarding (one-time, human-driven)

```mermaid
sequenceDiagram
    participant Human
    participant CLI as Onboarding CLI
    participant Browser
    participant Google as Google OAuth
    participant Creds as Credential Store
    participant Keychain as OS Keychain

    Human->>CLI: uv run onboard-google --account me@x.com
    CLI->>Browser: open consent URL (scopes: gmail.readonly, calendar, drive.readonly)
    Browser->>Google: human logs in, grants consent
    Google-->>Browser: redirect with auth code
    Browser-->>CLI: local redirect capture (loopback)
    CLI->>Google: exchange code for access_token + refresh_token
    Google-->>CLI: tokens
    CLI->>Creds: store(provider=google, account=me@x.com, tokens)
    Creds->>Keychain: write secret
    Keychain-->>Creds: ok
    CLI-->>Human: "me@x.com onboarded, scopes: [...]"
```

This CLI is never invoked by an agent — it's a separate entrypoint a human
runs interactively. Agents only ever see the *result* (tools become usable),
never the flow itself.

## Flow 4 — Token refresh (automatic, inside a tool call)

```mermaid
sequenceDiagram
    participant Adapter
    participant Creds as Credential Store
    participant TL as Token Lifecycle
    participant Keychain as OS Keychain
    participant Google as Google OAuth

    Adapter->>Creds: get_token(account, provider)
    Creds->>Keychain: read secret
    Keychain-->>Creds: token (expired)
    Creds->>TL: refresh(refresh_token)
    TL->>Google: POST /token (grant_type=refresh_token)
    alt refresh succeeds
        Google-->>TL: new access_token
        TL->>Creds: update stored token
        Creds->>Keychain: write secret
        Creds-->>Adapter: access_token
    else refresh_token revoked
        Google-->>TL: invalid_grant
        TL-->>Creds: raise NeedsReconsentError
        Creds-->>Adapter: raise NeedsReconsentError
        Adapter-->>Adapter: surfaces as tool error<br/>"re-run onboarding for this account"
    end
```

Failure mode is explicit and fails closed — never falls back to an
unauthenticated or cached-stale call.

---

## Repo layout

```
src/jb_gateway_mcp/
    server.py              # MCP server entrypoint, stdio transport, tool registration
    router.py               # dispatches tool calls -> policy check -> adapter
    policy.py                # loads policy.yaml, allow/deny decisions
    credentials.py            # keyring-backed store: get/put/refresh
    token_lifecycle.py         # refresh logic, NeedsReconsentError
    audit.py                    # structured JSONL logger, redaction
    adapters/
        base.py                   # Adapter protocol (tool name -> handler, required scope)
        google_gmail.py
        google_calendar.py
        google_drive.py
    cli/
        onboard_google.py          # OAuth consent flow entrypoint
tests/
    (mirrors src/ layout)
policy.yaml
pyproject.toml
```

## Policy model (`policy.yaml`)

Deny-by-default. Each caller identity maps to explicit tool + scope grants:

```yaml
callers:
  agent-x:
    allow:
      - tool: gmail.list_messages
        scope: gmail.readonly
      - tool: calendar.list_events
        scope: calendar.readonly
  agent-y:
    allow:
      - tool: gmail.send_message
        scope: gmail.send
```

Caller identity for stdio v1 = the local MCP client config name (process
launched Claude Desktop/Code side); no network auth needed since the OS
process boundary is the trust boundary. This field becomes a real
authenticated identity (API key/mTLS subject) once the networked-transport
phase lands — `router.py`/`policy.py` are written against an abstract
`caller_id: str` so that swap doesn't touch adapters.

## Security notes

- Tokens never appear in: tool responses, audit log entries, exceptions
  surfaced to the agent, or stdout/stderr.
- Audit log redacts by field name (`token`, `refresh_token`, `secret`,
  `authorization`) as a backstop, not just by convention.
- Adapters validate/sanitize all tool parameters at the boundary before
  building API requests (no raw param interpolation into URLs/queries).
- Financial adapters (later phase) are architecturally restricted to
  read-only HTTP verbs at the adapter base-class level, not just by policy
  config — so a policy misconfiguration can't grant a transfer capability
  that doesn't exist in code.

## Phased build order

1. Scaffolding — `uv init`, MCP server skeleton with one no-op tool, ruff/mypy/pytest wired.
2. Credential store + Google OAuth onboarding CLI.
3. Policy engine + audit log, wired into the router before any adapter runs.
4. Google adapters — Gmail (read/send), Calendar (read/write), Drive (read).
5. Tests + hardening — refresh failure paths, policy-deny paths, no-secret-in-logs check.
6. *(Future)* Networked transport (HTTP/SSE) + caller authentication.
7. *(Future)* Financial adapter — read-only, via an aggregator (e.g. Plaid).
