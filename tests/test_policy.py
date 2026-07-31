from pathlib import Path

import pytest

from jb_gateway_mcp.policy import PolicyEngine

VALID_POLICY = """
callers:
  agent-x:
    allow:
      - tool: gmail.list_messages
        scope: gmail.readonly
"""

MALFORMED_POLICY = """
callers:
  agent-x: [this, is, not, a, mapping
"""

EMPTY_CALLERS_POLICY = """
some_other_key: true
"""

REPO_POLICY_PATH = Path(__file__).resolve().parent.parent / "policy.yaml"


def _write(tmp_path: Path, content: str) -> Path:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(content)
    return policy_path


def test_known_caller_known_tool_allows_with_scope(tmp_path: Path) -> None:
    engine = PolicyEngine(_write(tmp_path, VALID_POLICY))
    decision = engine.check("agent-x", "gmail.list_messages")
    assert decision.allowed is True
    assert decision.scope == "gmail.readonly"


def test_unknown_caller_denies(tmp_path: Path) -> None:
    engine = PolicyEngine(_write(tmp_path, VALID_POLICY))
    decision = engine.check("agent-unknown", "gmail.list_messages")
    assert decision.allowed is False
    assert decision.scope is None
    assert "agent-unknown" in decision.reason


def test_known_caller_unknown_tool_denies(tmp_path: Path) -> None:
    engine = PolicyEngine(_write(tmp_path, VALID_POLICY))
    decision = engine.check("agent-x", "gmail.send_message")
    assert decision.allowed is False
    assert decision.scope is None
    assert "gmail.send_message" in decision.reason


def test_malformed_yaml_raises_at_construction(tmp_path: Path) -> None:
    policy_path = _write(tmp_path, MALFORMED_POLICY)
    with pytest.raises(ValueError):
        PolicyEngine(policy_path)


def test_missing_callers_key_loads_as_empty_but_valid(tmp_path: Path) -> None:
    engine = PolicyEngine(_write(tmp_path, EMPTY_CALLERS_POLICY))
    decision = engine.check("anyone", "anything")
    assert decision.allowed is False


def test_missing_policy_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        PolicyEngine(tmp_path / "does_not_exist.yaml")


def test_repo_policy_yaml_parses_successfully() -> None:
    engine = PolicyEngine(REPO_POLICY_PATH)
    decision = engine.check("anyone", "anything")
    assert decision.allowed is False
