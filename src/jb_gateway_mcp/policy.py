"""Deny-by-default policy engine backed by policy.yaml."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    scope: str | None
    reason: str


class PolicyEngine:
    """Loads policy.yaml and answers caller/tool authorization checks."""

    def __init__(self, policy_path: Path = Path("policy.yaml")) -> None:
        self._grants = self._load(policy_path)

    def _load(self, policy_path: Path) -> dict[str, dict[str, str]]:
        try:
            raw_text = policy_path.read_text()
        except OSError as exc:
            raise ValueError(f"cannot read policy file {policy_path}: {exc}") from exc

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"malformed policy YAML in {policy_path}: {exc}") from exc

        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f"policy file {policy_path} must contain a mapping at the top level")

        callers = data.get("callers") or {}
        if not isinstance(callers, dict):
            raise ValueError(f"'callers' in {policy_path} must be a mapping")

        grants: dict[str, dict[str, str]] = {}
        for caller_id, caller_config in callers.items():
            grants[caller_id] = self._parse_caller(caller_id, caller_config, policy_path)
        return grants

    def _parse_caller(
        self, caller_id: str, caller_config: Any, policy_path: Path
    ) -> dict[str, str]:
        if not isinstance(caller_config, dict):
            raise ValueError(f"caller '{caller_id}' in {policy_path} must be a mapping")

        allow_list = caller_config.get("allow") or []
        if not isinstance(allow_list, list):
            raise ValueError(f"caller '{caller_id}'.allow in {policy_path} must be a list")

        tool_scopes: dict[str, str] = {}
        for entry in allow_list:
            if not isinstance(entry, dict) or "tool" not in entry or "scope" not in entry:
                raise ValueError(
                    f"caller '{caller_id}' in {policy_path} has an allow entry "
                    "missing 'tool' or 'scope'"
                )
            tool_scopes[entry["tool"]] = entry["scope"]
        return tool_scopes

    def check(self, caller_id: str, tool_name: str) -> PolicyDecision:
        caller_grants = self._grants.get(caller_id)
        if caller_grants is None:
            return PolicyDecision(
                allowed=False,
                scope=None,
                reason=f"no grant for caller {caller_id} on tool {tool_name}",
            )

        scope = caller_grants.get(tool_name)
        if scope is None:
            return PolicyDecision(
                allowed=False,
                scope=None,
                reason=f"no grant for caller {caller_id} on tool {tool_name}",
            )

        return PolicyDecision(allowed=True, scope=scope, reason="granted by policy")
