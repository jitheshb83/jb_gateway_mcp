from __future__ import annotations

from datetime import UTC, datetime, timedelta

import keyring.errors
import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.credentials import (
    CredentialNotFoundError,
    CredentialStore,
    TokenRecord,
)
from jb_gateway_mcp.token_lifecycle import NeedsReconsentError

FAKE_ACCESS_TOKEN = "fake-access-token-do-not-leak"  # noqa: S105
FAKE_REFRESH_TOKEN = "fake-refresh-token-do-not-leak"  # noqa: S105


def _make_record(
    *,
    access_token: str = FAKE_ACCESS_TOKEN,
    refresh_token: str = FAKE_REFRESH_TOKEN,
    expires_at: datetime | None = None,
) -> TokenRecord:
    return TokenRecord(
        provider="google",
        account="me@example.com",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=1)),
        client_id="client-id",
        client_secret="client-secret",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token",
    )


def _fake_keyring_backend() -> tuple[dict[tuple[str, str], str], object, object]:
    """A minimal in-memory stand-in for keyring.set_password/get_password."""
    store: dict[tuple[str, str], str] = {}

    def set_password(service_name: str, username: str, password: str) -> None:
        store[(service_name, username)] = password

    def get_password(service_name: str, username: str) -> str | None:
        return store.get((service_name, username))

    return store, set_password, get_password


def test_put_get_round_trip(mocker: MockerFixture) -> None:
    store, set_password, get_password = _fake_keyring_backend()
    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)

    record = _make_record()
    cred_store = CredentialStore()
    cred_store.put_token(record)

    assert store  # something was written
    fetched = cred_store.get_token("google", "me@example.com")
    assert fetched == record


def test_get_token_raises_when_missing(mocker: MockerFixture) -> None:
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", return_value=None)

    cred_store = CredentialStore()
    with pytest.raises(CredentialNotFoundError):
        cred_store.get_token("google", "nobody@example.com")


def test_credential_not_found_error_omits_no_secret(mocker: MockerFixture) -> None:
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", return_value=None)

    cred_store = CredentialStore()
    with pytest.raises(CredentialNotFoundError) as exc_info:
        cred_store.get_token("google", "nobody@example.com")

    assert "google" in str(exc_info.value)
    assert "nobody@example.com" in str(exc_info.value)


def test_get_valid_token_returns_unexpired_token_without_refresh(mocker: MockerFixture) -> None:
    store, set_password, get_password = _fake_keyring_backend()
    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)
    refresh_mock = mocker.patch("jb_gateway_mcp.credentials.token_lifecycle.refresh_token")

    record = _make_record(expires_at=datetime.now(UTC) + timedelta(hours=1))
    cred_store = CredentialStore()
    cred_store.put_token(record)

    result = cred_store.get_valid_token("google", "me@example.com")

    assert result == record
    refresh_mock.assert_not_called()


def test_get_valid_token_refreshes_expired_token_and_persists(mocker: MockerFixture) -> None:
    store, set_password, get_password = _fake_keyring_backend()
    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)

    expired = _make_record(expires_at=datetime.now(UTC) - timedelta(minutes=5))
    refreshed = _make_record(
        access_token="new-access-token",  # noqa: S106
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    refresh_mock = mocker.patch(
        "jb_gateway_mcp.credentials.token_lifecycle.refresh_token", return_value=refreshed
    )

    cred_store = CredentialStore()
    cred_store.put_token(expired)

    result = cred_store.get_valid_token("google", "me@example.com")

    refresh_mock.assert_called_once_with(expired)
    assert result == refreshed
    # persisted record must reflect the refreshed token, not the stale one
    assert cred_store.get_token("google", "me@example.com") == refreshed


def test_get_valid_token_treats_near_expiry_as_expired(mocker: MockerFixture) -> None:
    """Within the clock-skew buffer, a token counts as expired and is refreshed."""
    store, set_password, get_password = _fake_keyring_backend()
    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)

    almost_expired = _make_record(expires_at=datetime.now(UTC) + timedelta(seconds=5))
    refreshed = _make_record(expires_at=datetime.now(UTC) + timedelta(hours=1))
    refresh_mock = mocker.patch(
        "jb_gateway_mcp.credentials.token_lifecycle.refresh_token", return_value=refreshed
    )

    cred_store = CredentialStore()
    cred_store.put_token(almost_expired)
    cred_store.get_valid_token("google", "me@example.com")

    refresh_mock.assert_called_once()


def test_get_valid_token_refresh_failure_does_not_update_store(mocker: MockerFixture) -> None:
    store, set_password, get_password = _fake_keyring_backend()
    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)

    expired = _make_record(expires_at=datetime.now(UTC) - timedelta(minutes=5))
    mocker.patch(
        "jb_gateway_mcp.credentials.token_lifecycle.refresh_token",
        side_effect=NeedsReconsentError("refresh token revoked"),
    )

    cred_store = CredentialStore()
    cred_store.put_token(expired)

    with pytest.raises(NeedsReconsentError):
        cred_store.get_valid_token("google", "me@example.com")

    # store must still hold the original (stale) record, not bad/partial data
    assert cred_store.get_token("google", "me@example.com") == expired


def test_delete_token_removes_stored_record(mocker: MockerFixture) -> None:
    store, set_password, get_password = _fake_keyring_backend()

    def delete_password(service_name: str, username: str) -> None:
        del store[(service_name, username)]

    mocker.patch("jb_gateway_mcp.credentials.keyring.set_password", side_effect=set_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.get_password", side_effect=get_password)
    mocker.patch("jb_gateway_mcp.credentials.keyring.delete_password", side_effect=delete_password)

    cred_store = CredentialStore()
    cred_store.put_token(_make_record())
    cred_store.delete_token("google", "me@example.com")

    assert store == {}
    with pytest.raises(CredentialNotFoundError):
        cred_store.get_token("google", "me@example.com")


def test_delete_token_raises_when_missing(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.credentials.keyring.delete_password",
        side_effect=keyring.errors.PasswordDeleteError,
    )

    cred_store = CredentialStore()
    with pytest.raises(CredentialNotFoundError):
        cred_store.delete_token("google", "nobody@example.com")


def test_token_record_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TokenRecord(
            provider="google",
            account="me@example.com",
            access_token=FAKE_ACCESS_TOKEN,
            refresh_token=FAKE_REFRESH_TOKEN,
            expires_at=datetime.now(),  # noqa: DTZ005 - intentionally naive for this test
            client_id="client-id",
            client_secret="client-secret",  # noqa: S106
            token_uri="https://oauth2.googleapis.com/token",
        )
