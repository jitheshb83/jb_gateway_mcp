from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from pytest_mock import MockerFixture

from jb_gateway_mcp.adapters.base import ToolSpec, build_google_client
from jb_gateway_mcp.credentials import CredentialStore, TokenRecord


def _make_record(access_token: str = "tok-abc") -> TokenRecord:
    return TokenRecord(
        provider="google",
        account="me@example.com",
        access_token=access_token,
        refresh_token="refresh-token",  # noqa: S106
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        client_id="client-id",
        client_secret="client-secret",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token",
    )


def test_build_google_client_uses_valid_token_and_builds_client(mocker: MockerFixture) -> None:
    record = _make_record()
    store = MagicMock(spec=CredentialStore)
    store.get_valid_token.return_value = record

    fake_credentials = MagicMock()
    credentials_cls = mocker.patch(
        "jb_gateway_mcp.adapters.base.Credentials", return_value=fake_credentials
    )
    fake_client = MagicMock()
    build_mock = mocker.patch("jb_gateway_mcp.adapters.base.build", return_value=fake_client)

    result = build_google_client(store, "me@example.com", "gmail", "v1")

    store.get_valid_token.assert_called_once_with("google", "me@example.com")
    credentials_cls.assert_called_once_with(token="tok-abc")
    build_mock.assert_called_once_with(
        "gmail", "v1", credentials=fake_credentials, cache_discovery=False
    )
    assert result is fake_client


def test_build_google_client_never_leaks_token_into_google_client_call(
    mocker: MockerFixture,
) -> None:
    """The raw access token must reach Credentials(), never `build()` directly."""
    record = _make_record(access_token="super-secret-token")
    store = MagicMock(spec=CredentialStore)
    store.get_valid_token.return_value = record

    mocker.patch("jb_gateway_mcp.adapters.base.Credentials", return_value=MagicMock())
    build_mock = mocker.patch("jb_gateway_mcp.adapters.base.build", return_value=MagicMock())

    build_google_client(store, "me@example.com", "drive", "v3")

    for call_args in build_mock.call_args_list:
        assert "super-secret-token" not in call_args.args
        assert "super-secret-token" not in call_args.kwargs.values()


def test_tool_spec_is_frozen_and_comparable() -> None:
    spec_a = ToolSpec(name="gmail.list_messages", scope="gmail.readonly", description="d")
    spec_b = ToolSpec(name="gmail.list_messages", scope="gmail.readonly", description="d")
    assert spec_a == spec_b
