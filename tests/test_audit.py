import json
from pathlib import Path

from jb_gateway_mcp.audit import AuditLogger

FAKE_SECRET = "sk-fake-secret-value-12345"


def test_log_entry_written_as_valid_json_with_expected_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    logger.log("agent-x", "gmail.list_messages", {"query": "is:unread"}, outcome="success")

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["caller"] == "agent-x"
    assert entry["tool"] == "gmail.list_messages"
    assert entry["outcome"] == "success"
    assert entry["params"] == {"query": "is:unread"}
    assert "ts" in entry and isinstance(entry["ts"], str)


def test_redaction_hides_top_level_sensitive_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    sensitive_keys = [
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
        "password",
        "api_key",
        "TOKEN",
        "Api_Key",
    ]
    params = {key: FAKE_SECRET for key in sensitive_keys}
    logger.log("agent-x", "some.tool", params, outcome="success")

    entry = json.loads(log_path.read_text().splitlines()[0])
    for key in sensitive_keys:
        assert entry["params"][key] == "[REDACTED]"


def test_redaction_hides_values_nested_in_dict_within_dict(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    params = {"outer": {"inner": {"refresh_token": FAKE_SECRET, "safe": "ok"}}}
    logger.log("agent-x", "some.tool", params, outcome="success")

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert entry["params"]["outer"]["inner"]["refresh_token"] == "[REDACTED]"
    assert entry["params"]["outer"]["inner"]["safe"] == "ok"


def test_redaction_hides_values_nested_in_list_of_dicts(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    params = {"items": [{"api_key": FAKE_SECRET}, {"safe": "value"}]}
    logger.log("agent-x", "some.tool", params, outcome="success")

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert entry["params"]["items"][0]["api_key"] == "[REDACTED]"
    assert entry["params"]["items"][1]["safe"] == "value"


def test_non_serializable_param_value_does_not_crash(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    class Unserializable:
        def __str__(self) -> str:
            return "unserializable-repr"

    logger.log("agent-x", "some.tool", {"weird": Unserializable()}, outcome="success")

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert entry["params"]["weird"] == "unserializable-repr"


def test_fake_secret_never_appears_in_raw_log_file(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    logger.log(
        "agent-x",
        "some.tool",
        {"outer": {"nested_list": [{"access_token": FAKE_SECRET}]}},
        outcome="success",
    )

    raw_content = log_path.read_text()
    assert FAKE_SECRET not in raw_content


def test_log_appends_without_truncating_previous_entries(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)

    logger.log("agent-x", "tool.one", {}, outcome="success")
    logger.log("agent-x", "tool.two", {}, outcome="denied")

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["tool"] == "tool.one"
    assert json.loads(lines[1])["tool"] == "tool.two"
