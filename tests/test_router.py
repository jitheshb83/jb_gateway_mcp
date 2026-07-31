import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from jb_gateway_mcp.audit import AuditLogger
from jb_gateway_mcp.policy import PolicyEngine
from jb_gateway_mcp.router import ToolRouter

POLICY_YAML = """
callers:
  agent-x:
    allow:
      - tool: gmail.list_messages
        scope: gmail.readonly
"""


def _make_router(tmp_path: Path) -> tuple[ToolRouter, Path]:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(POLICY_YAML)
    log_path = tmp_path / "audit.jsonl"
    router = ToolRouter(PolicyEngine(policy_path), AuditLogger(log_path))
    return router, log_path


def _read_entries(log_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def test_allowed_call_invokes_handler_and_returns_result(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": []})
    router.register("gmail.list_messages", "gmail.readonly", handler)

    result = router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert result == {"messages": []}
    handler.assert_called_once_with(query="is:unread")
    entries = _read_entries(log_path)
    assert len(entries) == 1
    assert entries[0]["outcome"] == "success"


def test_denied_call_does_not_invoke_handler_and_logs_denied(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock()
    router.register("gmail.send_message", "gmail.send", handler)

    with pytest.raises(PermissionError):
        router.handle("agent-x", "gmail.send_message", {"to": "a@example.com"})

    handler.assert_not_called()
    entries = _read_entries(log_path)
    assert len(entries) == 1
    assert entries[0]["outcome"] == "denied"


def test_handler_raising_logs_error_and_propagates(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)

    def failing_handler(**kwargs: Any) -> None:
        raise RuntimeError("upstream API exploded")

    router.register("gmail.list_messages", "gmail.readonly", failing_handler)

    with pytest.raises(RuntimeError, match="upstream API exploded"):
        router.handle("agent-x", "gmail.list_messages", {})

    entries = _read_entries(log_path)
    assert len(entries) == 1
    assert entries[0]["outcome"] == "error"


def test_allowed_but_unregistered_tool_raises_clear_error(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)

    with pytest.raises(LookupError):
        router.handle("agent-x", "gmail.list_messages", {})

    # No handler exists to succeed or fail, so nothing should be logged as
    # success/error for this call — this is a startup config mismatch, not
    # a policy decision or a handler outcome.
    assert log_path.exists() is False or _read_entries(log_path) == []
