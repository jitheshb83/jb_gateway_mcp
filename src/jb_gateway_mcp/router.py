"""Single dispatch point for tool calls: policy check, then handler, then audit."""

import time
from collections.abc import Callable
from typing import Any

from jb_gateway_mcp.audit import AuditLogger
from jb_gateway_mcp.policy import PolicyEngine

_CacheKey = tuple[str, tuple[tuple[str, Any], ...]]


class ToolRouter:
    """Routes tool calls through policy enforcement and audit logging.

    Optionally caches a tool's result in memory for a caller-specified TTL
    (see `register`'s `cache_ttl_seconds`) — never persisted to disk, and
    cleared whenever this process restarts. Opt-in per tool, off by
    default; only meant for read-only, idempotent tools backed by a scarce
    upstream quota, never for anything that sends/writes. A cache hit is
    still audit-logged (outcome "cached") — every call is still tracked,
    it just didn't reach the handler.
    """

    def __init__(self, policy: PolicyEngine, audit: AuditLogger) -> None:
        self._policy = policy
        self._audit = audit
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._cache_ttl_seconds: dict[str, float] = {}
        self._cache: dict[_CacheKey, tuple[float, Any]] = {}

    def register(
        self,
        name: str,
        scope: str,
        handler: Callable[..., Any],
        cache_ttl_seconds: float | None = None,
    ) -> None:
        self._handlers[name] = handler
        if cache_ttl_seconds is not None:
            self._cache_ttl_seconds[name] = cache_ttl_seconds

    def _cache_key(self, tool_name: str, params: dict[str, Any]) -> _CacheKey:
        return (tool_name, tuple(sorted(params.items())))

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

        ttl = self._cache_ttl_seconds.get(tool_name)
        cache_key = self._cache_key(tool_name, params) if ttl is not None else None
        if cache_key is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                expires_at, cached_result = cached
                if time.monotonic() < expires_at:
                    self._audit.log(caller_id, tool_name, params, outcome="cached")
                    return cached_result
                del self._cache[cache_key]

        try:
            result = handler(**params)
        except Exception:
            self._audit.log(caller_id, tool_name, params, outcome="error")
            raise

        if cache_key is not None and ttl is not None:
            self._cache[cache_key] = (time.monotonic() + ttl, result)

        self._audit.log(caller_id, tool_name, params, outcome="success")
        return result
