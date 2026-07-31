from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from google.auth.exceptions import RefreshError
from pytest_mock import MockerFixture

from jb_gateway_mcp.credentials import TokenRecord
from jb_gateway_mcp.token_lifecycle import (
    NeedsReconsentError,
    TokenRefreshError,
    refresh_token,
)

FAKE_ACCESS_TOKEN = "fake-access-token-do-not-leak"  # noqa: S105
FAKE_REFRESH_TOKEN = "fake-refresh-token-do-not-leak"  # noqa: S105


def _make_record() -> TokenRecord:
    return TokenRecord(
        provider="google",
        account="me@example.com",
        access_token=FAKE_ACCESS_TOKEN,
        refresh_token=FAKE_REFRESH_TOKEN,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        client_id="client-id",
        client_secret="client-secret",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token",
    )


def test_refresh_token_success_updates_access_token_and_expiry(mocker: MockerFixture) -> None:
    record = _make_record()
    new_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    fake_credentials = mocker.Mock()
    fake_credentials.token = "new-access-token"
    fake_credentials.expiry = new_expiry
    fake_credentials.refresh_token = "new-refresh-token"

    def _refresh(_request: object) -> None:
        # simulate google-auth mutating the credentials object in place
        return None

    fake_credentials.refresh.side_effect = _refresh
    mocker.patch(
        "jb_gateway_mcp.token_lifecycle.Credentials", return_value=fake_credentials
    )

    result = refresh_token(record)

    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"
    assert result.expires_at == new_expiry.replace(tzinfo=UTC)
    assert result.provider == record.provider
    assert result.account == record.account
    fake_credentials.refresh.assert_called_once()


def test_refresh_token_keeps_old_refresh_token_if_none_returned(mocker: MockerFixture) -> None:
    record = _make_record()
    fake_credentials = mocker.Mock()
    fake_credentials.token = "new-access-token"
    fake_credentials.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    fake_credentials.refresh_token = None

    mocker.patch(
        "jb_gateway_mcp.token_lifecycle.Credentials", return_value=fake_credentials
    )

    result = refresh_token(record)

    assert result.refresh_token == record.refresh_token


def test_refresh_token_invalid_grant_raises_needs_reconsent(mocker: MockerFixture) -> None:
    record = _make_record()
    fake_credentials = mocker.Mock()
    fake_credentials.refresh.side_effect = RefreshError(  # type: ignore[no-untyped-call]
        "invalid_grant: Token has been expired or revoked."
    )
    mocker.patch(
        "jb_gateway_mcp.token_lifecycle.Credentials", return_value=fake_credentials
    )

    with pytest.raises(NeedsReconsentError) as exc_info:
        refresh_token(record)

    assert "google" in str(exc_info.value)
    assert "me@example.com" in str(exc_info.value)
    assert FAKE_REFRESH_TOKEN not in str(exc_info.value)
    assert FAKE_ACCESS_TOKEN not in str(exc_info.value)


def test_refresh_token_other_refresh_error_raises_token_refresh_error(
    mocker: MockerFixture,
) -> None:
    record = _make_record()
    fake_credentials = mocker.Mock()
    fake_credentials.refresh.side_effect = RefreshError(  # type: ignore[no-untyped-call]
        "server_error: try again later"
    )
    mocker.patch(
        "jb_gateway_mcp.token_lifecycle.Credentials", return_value=fake_credentials
    )

    with pytest.raises(TokenRefreshError):
        refresh_token(record)


def test_refresh_token_unsupported_provider_raises_token_refresh_error() -> None:
    record = TokenRecord(
        provider="not-google",
        account="me@example.com",
        access_token=FAKE_ACCESS_TOKEN,
        refresh_token=FAKE_REFRESH_TOKEN,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        client_id="client-id",
        client_secret="client-secret",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token",
    )

    with pytest.raises(TokenRefreshError):
        refresh_token(record)


def test_refresh_token_missing_expiry_raises_token_refresh_error(mocker: MockerFixture) -> None:
    record = _make_record()
    fake_credentials = mocker.Mock()
    fake_credentials.token = "new-access-token"
    fake_credentials.expiry = None
    fake_credentials.refresh_token = "new-refresh-token"
    mocker.patch(
        "jb_gateway_mcp.token_lifecycle.Credentials", return_value=fake_credentials
    )

    with pytest.raises(TokenRefreshError):
        refresh_token(record)
