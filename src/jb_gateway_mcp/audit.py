"""Structured JSONL audit logging with secret redaction."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "authorization",
    "password",
    "api_key",
}

_REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (_REDACTED if key.lower() in _SENSITIVE_KEYS else _redact(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class AuditLogger:
    """Appends one redacted JSON object per line to a JSONL file."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    def log(self, caller: str, tool: str, params: dict[str, Any], outcome: str) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "caller": caller,
            "tool": tool,
            "outcome": outcome,
            "params": _redact(params),
        }
        line = json.dumps(entry, default=str)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
