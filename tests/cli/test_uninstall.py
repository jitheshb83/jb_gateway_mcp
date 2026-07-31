from __future__ import annotations

import urllib.error
from datetime import UTC, datetime, timedelta

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.cli.uninstall import main
from jb_gateway_mcp.credentials import CredentialNotFoundError, TokenRecord

FAKE_ACCESS_TOKEN = "fake-access-token-do-not-leak"  # noqa: S105
FAKE_REFRESH_TOKEN = "fake-refresh-token-do-not-leak"  # noqa: S105


def _fake_record(account: str = "me@example.com") -> TokenRecord:
    return TokenRecord(
        provider="google",
        account=account,
        access_token=FAKE_ACCESS_TOKEN,
        refresh_token=FAKE_REFRESH_TOKEN,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        client_id="client-id",
        client_secret="client-secret",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token",
    )


def _run(mocker: MockerFixture, args: list[str]) -> None:
    mocker.patch("sys.argv", ["uninstall-google", *args])
    main()


def test_yes_flag_revokes_and_deletes_without_prompting(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token", return_value=_fake_record()
    )
    delete_token = mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    urlopen = mocker.patch("jb_gateway_mcp.cli.uninstall.urllib.request.urlopen")
    urlopen.return_value.__enter__.return_value.status = 200
    prompt = mocker.patch("builtins.input")

    _run(mocker, ["--account", "me@example.com", "--yes"])

    prompt.assert_not_called()
    urlopen.assert_called_once()
    delete_token.assert_called_once_with("google", "me@example.com")


def test_declining_prompt_skips_deletion(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token", return_value=_fake_record()
    )
    delete_token = mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    urlopen = mocker.patch("jb_gateway_mcp.cli.uninstall.urllib.request.urlopen")
    mocker.patch("builtins.input", return_value="n")

    _run(mocker, ["--account", "me@example.com"])

    urlopen.assert_not_called()
    delete_token.assert_not_called()


def test_missing_account_is_skipped_gracefully(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token",
        side_effect=CredentialNotFoundError("not found"),
    )
    delete_token = mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    urlopen = mocker.patch("jb_gateway_mcp.cli.uninstall.urllib.request.urlopen")

    _run(mocker, ["--account", "nobody@example.com", "--yes"])

    urlopen.assert_not_called()
    delete_token.assert_not_called()


def test_keep_remote_grant_skips_revoke_call(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token", return_value=_fake_record()
    )
    delete_token = mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    urlopen = mocker.patch("jb_gateway_mcp.cli.uninstall.urllib.request.urlopen")

    _run(mocker, ["--account", "me@example.com", "--yes", "--keep-remote-grant"])

    urlopen.assert_not_called()
    delete_token.assert_called_once_with("google", "me@example.com")


def test_remote_revoke_failure_still_deletes_locally(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token", return_value=_fake_record()
    )
    delete_token = mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.urllib.request.urlopen",
        side_effect=urllib.error.URLError("network down"),
    )

    _run(mocker, ["--account", "me@example.com", "--yes"])

    delete_token.assert_called_once_with("google", "me@example.com")
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert FAKE_ACCESS_TOKEN not in captured.out
    assert FAKE_REFRESH_TOKEN not in captured.out


def test_never_prints_token_values(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.uninstall.CredentialStore.get_token", return_value=_fake_record()
    )
    mocker.patch("jb_gateway_mcp.cli.uninstall.CredentialStore.delete_token")
    urlopen = mocker.patch("jb_gateway_mcp.cli.uninstall.urllib.request.urlopen")
    urlopen.return_value.__enter__.return_value.status = 200

    _run(mocker, ["--account", "me@example.com", "--yes"])

    captured = capsys.readouterr()
    assert FAKE_ACCESS_TOKEN not in captured.out
    assert FAKE_REFRESH_TOKEN not in captured.out
