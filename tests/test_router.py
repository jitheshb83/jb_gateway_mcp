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


def test_uncached_tool_always_invokes_handler(tmp_path: Path) -> None:
    """No cache_ttl_seconds passed to register -> identical to pre-caching
    behavior, every call reaches the handler."""
    router, _ = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": []})
    router.register("gmail.list_messages", "gmail.readonly", handler)

    router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert handler.call_count == 2


def test_cacheable_tool_second_identical_call_hits_cache(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": ["one"]})
    router.register("gmail.list_messages", "gmail.readonly", handler, cache_ttl_seconds=60.0)

    first = router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    second = router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert first == second == {"messages": ["one"]}
    handler.assert_called_once()  # second call served from cache, handler not re-invoked
    entries = _read_entries(log_path)
    assert [e["outcome"] for e in entries] == ["success", "cached"]
    # A cache hit is still a fully audited call, params and all.
    assert entries[1]["params"] == {"query": "is:unread"}


def test_cacheable_tool_different_params_is_a_cache_miss(tmp_path: Path) -> None:
    router, _ = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": []})
    router.register("gmail.list_messages", "gmail.readonly", handler, cache_ttl_seconds=60.0)

    router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    router.handle("agent-x", "gmail.list_messages", {"query": "is:read"})

    assert handler.call_count == 2


def test_cacheable_tool_expired_entry_is_a_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": []})
    router.register("gmail.list_messages", "gmail.readonly", handler, cache_ttl_seconds=60.0)

    clock = [1000.0]
    monkeypatch.setattr("jb_gateway_mcp.router.time.monotonic", lambda: clock[0])

    router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    clock[0] += 61.0  # past the 60s TTL
    router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert handler.call_count == 2
    entries = _read_entries(log_path)
    assert [e["outcome"] for e in entries] == ["success", "success"]


def test_cacheable_tool_error_is_not_cached(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock(side_effect=RuntimeError("upstream exploded"))
    router.register("gmail.list_messages", "gmail.readonly", handler, cache_ttl_seconds=60.0)

    with pytest.raises(RuntimeError):
        router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    with pytest.raises(RuntimeError):
        router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert handler.call_count == 2  # a failed call must never poison the cache
    entries = _read_entries(log_path)
    assert [e["outcome"] for e in entries] == ["error", "error"]


def test_cache_hit_returns_a_copy_mutation_safe(tmp_path: Path) -> None:
    """A caller mutating its "own" cached result in place must never
    corrupt what the next caller sees during the same TTL window."""
    router, _ = _make_router(tmp_path)
    handler = MagicMock(return_value={"messages": ["one"]})
    router.register("gmail.list_messages", "gmail.readonly", handler, cache_ttl_seconds=60.0)

    first = router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})
    first["messages"].append("mutated by caller")

    second = router.handle("agent-x", "gmail.list_messages", {"query": "is:unread"})

    assert second == {"messages": ["one"]}
    assert first != second  # confirms it was a real, independent copy


def test_denied_call_never_reaches_or_populates_cache(tmp_path: Path) -> None:
    router, log_path = _make_router(tmp_path)
    handler = MagicMock(return_value={"ok": True})
    router.register("gmail.send_message", "gmail.send", handler, cache_ttl_seconds=60.0)

    with pytest.raises(PermissionError):
        router.handle("agent-x", "gmail.send_message", {"to": "a@example.com"})

    handler.assert_not_called()
    entries = _read_entries(log_path)
    assert [e["outcome"] for e in entries] == ["denied"]
