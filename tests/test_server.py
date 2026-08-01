import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pytest_mock import MockerFixture

from jb_gateway_mcp import server
from jb_gateway_mcp.adapters import enable_banking, google_calendar, google_drive, google_gmail
from jb_gateway_mcp.policy import PolicyEngine


@pytest.mark.anyio
async def test_ping_over_stdio(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    # The subprocess only inherits an allowlisted env subset (see
    # mcp.client.stdio.get_default_environment), so JB_GATEWAY_AUDIT_LOG must
    # be passed explicitly to keep this test from writing into the real
    # user home directory.
    params = StdioServerParameters(
        command=uv,
        args=["run", "jb-gateway-mcp"],
        env={"JB_GATEWAY_AUDIT_LOG": str(tmp_path / "audit.jsonl")},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert any(t.name == "ping" for t in tools.tools)

        result = await session.call_tool("ping", {})
        assert result.content[0].text == "pong"  # type: ignore[union-attr]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


ALL_ADAPTER_MODULES = (google_gmail, google_calendar, google_drive, enable_banking)

# (wrapper function, expected router tool name, kwargs it should be called with)
WRAPPER_CASES: list[tuple[Any, str, dict[str, Any]]] = [
    (
        server.gmail_list_messages,
        "gmail.list_messages",
        {"account": "me@example.com", "query": "is:unread"},
    ),
    (
        server.gmail_read_message,
        "gmail.read_message",
        {"account": "me@example.com", "message_id": "m1"},
    ),
    (
        server.gmail_send_message,
        "gmail.send_message",
        {"account": "me@example.com", "to": "b@example.com", "subject": "hi", "body": "text"},
    ),
    (
        server.calendar_list_events,
        "calendar.list_events",
        {"account": "me@example.com", "calendar_id": "primary", "max_results": 10},
    ),
    (
        server.calendar_create_event,
        "calendar.create_event",
        {
            "account": "me@example.com",
            "calendar_id": "primary",
            "summary": "s",
            "start_iso": "2026-08-01T10:00:00+00:00",
            "end_iso": "2026-08-01T11:00:00+00:00",
        },
    ),
    (
        server.drive_list_files,
        "drive.list_files",
        {"account": "me@example.com", "query": "", "page_size": 20},
    ),
    (
        server.drive_read_file,
        "drive.read_file",
        {"account": "me@example.com", "file_id": "f1"},
    ),
    (
        server.bank_list_accounts,
        "bank.list_accounts",
        {"institution": "dnb"},
    ),
    (
        server.bank_get_balance,
        "bank.get_balance",
        {"institution": "dnb", "account_uid": "acc-1"},
    ),
    (
        server.bank_summarize_spending,
        "bank.summarize_spending",
        {
            "institution": "dnb",
            "account_uid": "acc-1",
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
        },
    ),
    (
        server.bank_list_transactions_summary,
        "bank.list_transactions_summary",
        {
            "institution": "dnb",
            "account_uid": "acc-1",
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
        },
    ),
    (
        server.bank_list_transactions_detailed,
        "bank.list_transactions_detailed",
        {
            "institution": "dnb",
            "account_uid": "acc-1",
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
        },
    ),
]


@pytest.mark.parametrize(
    ("wrapper", "tool_name", "kwargs"),
    WRAPPER_CASES,
    ids=[case[1] for case in WRAPPER_CASES],
)
def test_wrapper_calls_router_handle_with_expected_tool_and_params(
    wrapper: Any, tool_name: str, kwargs: dict[str, Any], mocker: MockerFixture
) -> None:
    handle_mock = mocker.patch.object(server.router, "handle", return_value={"ok": True})

    result = wrapper(**kwargs)

    handle_mock.assert_called_once_with(server.CALLER_ID, tool_name, kwargs)
    assert result == {"ok": True}


def test_default_policy_denies_unconfigured_caller_for_every_registered_tool(
    tmp_path: Path,
) -> None:
    """The gateway ships safe-by-default: a caller with no policy grants gets
    denied on every real tool, even after adapters are wired in.

    Uses a blank fixture policy rather than the repo's live policy.yaml —
    that file is meant to be edited by whoever deploys this server (see
    README.md), so it can't double as a "ships with nothing granted" fixture.
    """
    empty_policy_path = tmp_path / "empty_policy.yaml"
    empty_policy_path.write_text("callers: {}\n")
    policy = PolicyEngine(empty_policy_path)

    tool_names = [spec.name for module in ALL_ADAPTER_MODULES for spec in module.TOOLS]
    assert tool_names  # sanity: adapters actually register tools

    for tool_name in tool_names:
        decision = policy.check("unconfigured-caller", tool_name)
        assert decision.allowed is False
