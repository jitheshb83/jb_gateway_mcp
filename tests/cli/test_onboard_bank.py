from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.cli.onboard_bank import _resolve_aspsp, main
from jb_gateway_mcp.credentials_bank import (
    AppCredential,
    BankCredentialNotFoundError,
    BankSession,
)

FAKE_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n"
FAKE_JWT = "fake.jwt.do-not-leak"  # noqa: S105
FAKE_SESSION_ID = "session-do-not-leak"


def _fake_response(json_payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_payload
    response.raise_for_status.return_value = None
    return response


def _patch_common(mocker: MockerFixture) -> dict[str, MagicMock]:
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.mint_jwt", return_value=FAKE_JWT)
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.webbrowser.open")

    get_mock = mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response({"aspsps": [{"name": "DNB Bank ASA", "country": "NO"}]}),
    )
    post_mock = mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.post",
        side_effect=[
            _fake_response({"url": "https://bank.example/auth?x=1"}),
            _fake_response(
                {
                    "session_id": FAKE_SESSION_ID,
                    "accounts": [
                        {
                            "uid": "acc-1",
                            "account_id": {"iban": "NO9386011117947"},
                            "name": "Checking",
                            "currency": "NOK",
                        }
                    ],
                    "access": {"valid_until": (datetime.now(UTC) + timedelta(days=90)).isoformat()},
                }
            ),
        ],
    )
    mocker.patch(
        "builtins.input",
        return_value="https://localhost:8080/callback?code=auth-code-123&state=x",
    )
    return {"get": get_mock, "post": post_mock}


def test_first_run_stores_app_credential_and_session_and_prints_no_secrets(
    mocker: MockerFixture, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_path = tmp_path / "key.pem"
    key_path.write_text(FAKE_PRIVATE_KEY)

    _patch_common(mocker)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        side_effect=BankCredentialNotFoundError("none stored"),
    )
    put_app = mocker.patch("jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.put_app_credential")
    put_session = mocker.patch("jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.put_session")

    mocker.patch(
        "sys.argv",
        [
            "onboard-bank",
            "--institution",
            "dnb",
            "--application-id",
            "app-123",
            "--private-key",
            str(key_path),
        ],
    )

    main()

    put_app.assert_called_once()
    (stored_app,) = put_app.call_args.args
    assert isinstance(stored_app, AppCredential)
    assert stored_app.application_id == "app-123"
    assert stored_app.private_key_pem == FAKE_PRIVATE_KEY

    put_session.assert_called_once()
    (stored_session,) = put_session.call_args.args
    assert isinstance(stored_session, BankSession)
    assert stored_session.institution == "dnb"
    assert stored_session.session_id == FAKE_SESSION_ID
    assert len(stored_session.accounts) == 1
    assert stored_session.accounts[0].uid == "acc-1"
    masked_iban = stored_session.accounts[0].masked_iban
    assert masked_iban is not None
    assert "7947" in masked_iban.replace(" ", "")
    assert "NO9386011117947" not in masked_iban

    captured = capsys.readouterr()
    assert "dnb" in captured.out
    assert FAKE_PRIVATE_KEY not in captured.out
    assert FAKE_JWT not in captured.out
    assert FAKE_SESSION_ID not in captured.out
    assert "NO9386011117947" not in captured.out


def test_missing_app_credential_without_flags_exits(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        side_effect=BankCredentialNotFoundError("none stored"),
    )
    mocker.patch("sys.argv", ["onboard-bank", "--institution", "dnb"])

    with pytest.raises(SystemExit):
        main()


def test_subsequent_run_reuses_stored_app_credential(mocker: MockerFixture) -> None:
    existing = AppCredential(application_id="app-123", private_key_pem=FAKE_PRIVATE_KEY)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        return_value=existing,
    )
    put_app = mocker.patch("jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.put_app_credential")
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.put_session")

    _patch_common(mocker)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response({"aspsps": [{"name": "Nordea Bank Abp", "country": "NO"}]}),
    )
    mocker.patch("sys.argv", ["onboard-bank", "--institution", "nordea"])

    main()

    put_app.assert_not_called()  # no re-registration when a credential is already stored


def test_exact_name_match_resolves_despite_ambiguous_substring(mocker: MockerFixture) -> None:
    """Real-world case: Enable Banking's NO list has both "DNB" and "DNB
    Corporate Mastercard" — the substring "dnb" matches both, but the exact
    (case-insensitive) name match must resolve cleanly to plain "DNB".
    """
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.mint_jwt", return_value=FAKE_JWT)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response(
            {"aspsps": [{"name": "DNB"}, {"name": "DNB Corporate Mastercard"}]}
        ),
    )

    aspsp = _resolve_aspsp(
        AppCredential(application_id="app-123", private_key_pem=FAKE_PRIVATE_KEY), "dnb"
    )

    assert aspsp == {"name": "DNB", "country": "NO"}


def test_ambiguous_aspsp_match_exits(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        return_value=AppCredential(application_id="app-123", private_key_pem=FAKE_PRIVATE_KEY),
    )
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.mint_jwt", return_value=FAKE_JWT)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response(
            {"aspsps": [{"name": "DNB Bank ASA"}, {"name": "DNB Boligkreditt"}]}
        ),
    )
    mocker.patch("sys.argv", ["onboard-bank", "--institution", "dnb"])

    with pytest.raises(SystemExit):
        main()


def test_no_aspsp_match_exits(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        return_value=AppCredential(application_id="app-123", private_key_pem=FAKE_PRIVATE_KEY),
    )
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.mint_jwt", return_value=FAKE_JWT)
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response({"aspsps": []}),
    )
    mocker.patch("sys.argv", ["onboard-bank", "--institution", "dnb"])

    with pytest.raises(SystemExit):
        main()


def test_pasted_url_without_code_exits(mocker: MockerFixture) -> None:
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.BankCredentialStore.get_app_credential",
        return_value=AppCredential(application_id="app-123", private_key_pem=FAKE_PRIVATE_KEY),
    )
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.mint_jwt", return_value=FAKE_JWT)
    mocker.patch("jb_gateway_mcp.cli.onboard_bank.webbrowser.open")
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.get",
        return_value=_fake_response({"aspsps": [{"name": "DNB Bank ASA"}]}),
    )
    mocker.patch(
        "jb_gateway_mcp.cli.onboard_bank.httpx.post",
        return_value=_fake_response({"url": "https://bank.example/auth"}),
    )
    mocker.patch("builtins.input", return_value="https://localhost:8080/callback?state=x")
    mocker.patch("sys.argv", ["onboard-bank", "--institution", "dnb"])

    with pytest.raises(SystemExit):
        main()
