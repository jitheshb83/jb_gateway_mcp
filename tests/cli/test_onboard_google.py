from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.cli.onboard_google import _DEFAULT_SCOPES, main
from jb_gateway_mcp.credentials import TokenRecord

FAKE_ACCESS_TOKEN = "fake-access-token-do-not-leak"  # noqa: S105
FAKE_REFRESH_TOKEN = "fake-refresh-token-do-not-leak"  # noqa: S105
FAKE_CLIENT_SECRET = "fake-client-secret-do-not-leak"  # noqa: S105


def _fake_oauth_credentials(
    mocker: MockerFixture,
    *,
    refresh_token: str | None = FAKE_REFRESH_TOKEN,
    expiry: datetime | None = None,
) -> object:
    creds = mocker.Mock()
    creds.token = FAKE_ACCESS_TOKEN
    creds.refresh_token = refresh_token
    creds.expiry = expiry if expiry is not None else (datetime.now() + timedelta(hours=1))
    creds.client_id = "client-id"
    creds.client_secret = FAKE_CLIENT_SECRET
    creds.token_uri = "https://oauth2.googleapis.com/token"
    return creds


def test_main_stores_token_and_prints_no_secrets(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_flow = mocker.Mock()
    fake_flow.run_local_server = mocker.Mock()
    fake_flow.credentials = _fake_oauth_credentials(mocker)
    from_secrets = mocker.patch(
        "jb_gateway_mcp.cli.onboard_google.InstalledAppFlow.from_client_secrets_file",
        return_value=fake_flow,
    )
    put_token = mocker.patch("jb_gateway_mcp.cli.onboard_google.CredentialStore.put_token")

    mocker.patch(
        "sys.argv",
        [
            "onboard-google",
            "--account",
            "me@example.com",
            "--client-secrets",
            "/tmp/client_secret.json",
        ],
    )

    main()

    from_secrets.assert_called_once()
    assert from_secrets.call_args.kwargs["scopes"] == _DEFAULT_SCOPES
    fake_flow.run_local_server.assert_called_once()

    put_token.assert_called_once()
    (stored_record,) = put_token.call_args.args
    assert isinstance(stored_record, TokenRecord)
    assert stored_record.provider == "google"
    assert stored_record.account == "me@example.com"
    assert stored_record.access_token == FAKE_ACCESS_TOKEN
    assert stored_record.refresh_token == FAKE_REFRESH_TOKEN
    assert stored_record.expires_at.tzinfo is not None

    captured = capsys.readouterr()
    assert "me@example.com" in captured.out
    assert FAKE_ACCESS_TOKEN not in captured.out
    assert FAKE_REFRESH_TOKEN not in captured.out
    assert FAKE_CLIENT_SECRET not in captured.out


def test_main_custom_scopes(mocker: MockerFixture) -> None:
    fake_flow = mocker.Mock()
    fake_flow.run_local_server = mocker.Mock()
    fake_flow.credentials = _fake_oauth_credentials(mocker)
    from_secrets = mocker.patch(
        "jb_gateway_mcp.cli.onboard_google.InstalledAppFlow.from_client_secrets_file",
        return_value=fake_flow,
    )
    mocker.patch("jb_gateway_mcp.cli.onboard_google.CredentialStore.put_token")

    mocker.patch(
        "sys.argv",
        [
            "onboard-google",
            "--account",
            "me@example.com",
            "--client-secrets",
            "/tmp/client_secret.json",
            "--scopes",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )

    main()

    assert from_secrets.call_args.kwargs["scopes"] == [
        "https://www.googleapis.com/auth/gmail.send"
    ]


def test_main_raises_without_refresh_token(mocker: MockerFixture) -> None:
    fake_flow = mocker.Mock()
    fake_flow.run_local_server = mocker.Mock()
    fake_flow.credentials = _fake_oauth_credentials(mocker, refresh_token=None)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_google.InstalledAppFlow.from_client_secrets_file",
        return_value=fake_flow,
    )
    put_token = mocker.patch("jb_gateway_mcp.cli.onboard_google.CredentialStore.put_token")

    mocker.patch(
        "sys.argv",
        [
            "onboard-google",
            "--account",
            "me@example.com",
            "--client-secrets",
            "/tmp/client_secret.json",
        ],
    )

    with pytest.raises(RuntimeError):
        main()

    put_token.assert_not_called()
