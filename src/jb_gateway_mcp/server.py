import os
from pathlib import Path
from typing import Any, cast

from mcp.server.mcpserver import MCPServer

from jb_gateway_mcp.adapters import enable_banking, google_calendar, google_drive, google_gmail
from jb_gateway_mcp.audit import AuditLogger
from jb_gateway_mcp.credentials import CredentialStore
from jb_gateway_mcp.credentials_bank import BankCredentialStore
from jb_gateway_mcp.policy import PolicyEngine
from jb_gateway_mcp.router import ToolRouter

mcp = MCPServer("jb-gateway-mcp")

# stdio v1 caller identity: the OS process boundary is the trust boundary, so a
# stable string set by whoever launches this process is enough for policy/audit
# (see DESIGN.md section 7). Read once at startup, used for every tool call.
CALLER_ID = os.environ.get("JB_GATEWAY_CALLER_ID", "local")

_policy_path = Path(
    os.environ.get("JB_GATEWAY_POLICY_FILE", str(Path.home() / ".jb_gateway_mcp" / "policy.yaml"))
)
_audit_path = Path(
    os.environ.get("JB_GATEWAY_AUDIT_LOG", str(Path.home() / ".jb_gateway_mcp" / "audit.jsonl"))
)
_audit_path.parent.mkdir(parents=True, exist_ok=True)

credential_store = CredentialStore()
bank_credential_store = BankCredentialStore()
policy = PolicyEngine(_policy_path)
audit = AuditLogger(_audit_path)
router = ToolRouter(policy, audit)

for _module in (google_gmail, google_calendar, google_drive):
    _handlers = _module.get_handlers(credential_store)
    for _spec in _module.TOOLS:
        router.register(_spec.name, _spec.scope, _handlers[_spec.name])

_bank_handlers = enable_banking.get_handlers(bank_credential_store)
for _spec in enable_banking.TOOLS:
    router.register(_spec.name, _spec.scope, _bank_handlers[_spec.name])


@mcp.tool()
def ping() -> str:
    """Smoke-test tool confirming the gateway process is reachable."""
    return "pong"


@mcp.tool(name="gmail.list_messages")
def gmail_list_messages(account: str, query: str = "") -> list[dict[str, Any]]:
    """List Gmail messages for an account, optionally filtered by query."""
    params = {"account": account, "query": query}
    return cast(list[dict[str, Any]], router.handle(CALLER_ID, "gmail.list_messages", params))


@mcp.tool(name="gmail.read_message")
def gmail_read_message(account: str, message_id: str) -> dict[str, Any]:
    """Read a single Gmail message's subject/from/snippet/body."""
    params = {"account": account, "message_id": message_id}
    return cast(dict[str, Any], router.handle(CALLER_ID, "gmail.read_message", params))


@mcp.tool(name="gmail.send_message")
def gmail_send_message(account: str, to: str, subject: str, body: str) -> dict[str, Any]:
    """Send an email from an account."""
    params = {"account": account, "to": to, "subject": subject, "body": body}
    return cast(dict[str, Any], router.handle(CALLER_ID, "gmail.send_message", params))


@mcp.tool(name="calendar.list_events")
def calendar_list_events(
    account: str, calendar_id: str = "primary", max_results: int = 10
) -> list[dict[str, Any]]:
    """List upcoming events on a calendar."""
    params = {"account": account, "calendar_id": calendar_id, "max_results": max_results}
    return cast(list[dict[str, Any]], router.handle(CALLER_ID, "calendar.list_events", params))


@mcp.tool(name="calendar.create_event")
def calendar_create_event(
    account: str, calendar_id: str, summary: str, start_iso: str, end_iso: str
) -> dict[str, Any]:
    """Create a new calendar event."""
    params = {
        "account": account,
        "calendar_id": calendar_id,
        "summary": summary,
        "start_iso": start_iso,
        "end_iso": end_iso,
    }
    return cast(dict[str, Any], router.handle(CALLER_ID, "calendar.create_event", params))


@mcp.tool(name="drive.list_files")
def drive_list_files(account: str, query: str = "", page_size: int = 20) -> list[dict[str, Any]]:
    """List Drive files matching a query."""
    params = {"account": account, "query": query, "page_size": page_size}
    return cast(list[dict[str, Any]], router.handle(CALLER_ID, "drive.list_files", params))


@mcp.tool(name="drive.read_file")
def drive_read_file(account: str, file_id: str) -> dict[str, Any]:
    """Read metadata and text content of a Drive file."""
    params = {"account": account, "file_id": file_id}
    return cast(dict[str, Any], router.handle(CALLER_ID, "drive.read_file", params))


@mcp.tool(name="bank.list_accounts")
def bank_list_accounts(institution: str) -> list[dict[str, Any]]:
    """List linked bank accounts for an institution (masked IBAN)."""
    params = {"institution": institution}
    return cast(list[dict[str, Any]], router.handle(CALLER_ID, "bank.list_accounts", params))


@mcp.tool(name="bank.get_balance")
def bank_get_balance(institution: str, account_uid: str) -> list[dict[str, Any]]:
    """Get current/available balances for a bank account."""
    params = {"institution": institution, "account_uid": account_uid}
    return cast(list[dict[str, Any]], router.handle(CALLER_ID, "bank.get_balance", params))


@mcp.tool(name="bank.summarize_spending")
def bank_summarize_spending(
    institution: str, account_uid: str, date_from: str, date_to: str
) -> dict[str, Any]:
    """Aggregate total in/out/net spending for a date range (no transaction detail)."""
    params = {
        "institution": institution,
        "account_uid": account_uid,
        "date_from": date_from,
        "date_to": date_to,
    }
    return cast(dict[str, Any], router.handle(CALLER_ID, "bank.summarize_spending", params))


@mcp.tool(name="bank.list_transactions_summary")
def bank_list_transactions_summary(
    institution: str, account_uid: str, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    """List transactions for a date range: date, amount, currency only."""
    params = {
        "institution": institution,
        "account_uid": account_uid,
        "date_from": date_from,
        "date_to": date_to,
    }
    return cast(
        list[dict[str, Any]],
        router.handle(CALLER_ID, "bank.list_transactions_summary", params),
    )


@mcp.tool(name="bank.list_transactions_detailed")
def bank_list_transactions_detailed(
    institution: str, account_uid: str, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    """List transactions including counterparty name/description (IBANs still masked)."""
    params = {
        "institution": institution,
        "account_uid": account_uid,
        "date_from": date_from,
        "date_to": date_to,
    }
    return cast(
        list[dict[str, Any]],
        router.handle(CALLER_ID, "bank.list_transactions_detailed", params),
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
