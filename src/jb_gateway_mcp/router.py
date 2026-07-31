"""Single dispatch point for tool calls: policy check, then handler, then audit."""

from collections.abc import Callable
from typing import Any

from jb_gateway_mcp.audit import AuditLogger
from jb_gateway_mcp.policy import PolicyEngine


class ToolRouter:
    """Routes tool calls through policy enforcement and audit logging."""

    def __init__(self, policy: PolicyEngine, audit: AuditLogger) -> None:
        self._policy = policy
        self._audit = audit
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, scope: str, handler: Callable[..., Any]) -> None:
        self._handlers[name] = handler

    def handle(self, caller_id: str, tool_name: str, params: dict[str, Any]) -> Any:
        decision = self._policy.check(caller_id, tool_name)

        if not decision.allowed:
            self._audit.log(caller_id, tool_name, params, outcome="denied")
            raise PermissionError(decision.reason)

        handler = self._handlers.get(tool_name)
        if handler is None:
            raise LookupError(
                f"tool '{tool_name}' is granted by policy but has no registered handler"
            )

        try:
            result = handler(**params)
        except Exception:
            self._audit.log(caller_id, tool_name, params, outcome="error")
            raise

        self._audit.log(caller_id, tool_name, params, outcome="success")
        return result
