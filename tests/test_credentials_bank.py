from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pytest_mock import MockerFixture

from jb_gateway_mcp.credentials_bank import (
    AppCredential,
    BankAccount,
    BankCredentialNotFoundError,
    BankCredentialStore,
    BankSession,
    NeedsReconsentError,
    mask_iban,
    mint_jwt,
)


def _generate_key_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _fake_keyring_backend() -> tuple[dict[tuple[str, str], str], object, object]:
    store: dict[tuple[str, str], str] = {}

    def set_password(service_name: str, username: str, password: str) -> None:
        store[(service_name, username)] = password

    def get_password(service_name: str, username: str) -> str | None:
        return store.get((service_name, username))

    return store, set_password, get_password


def _make_session(*, valid_until: datetime | None = None) -> BankSession:
    return BankSession(
        institution="dnb",
        session_id="session-do-not-leak",
        accounts=(
            BankAccount(
                uid="acc-1", masked_iban="**** **** **** 6538", name="Checking", currency="NOK"
            ),
        ),
        valid_until=valid_until or (datetime.now(UTC) + timedelta(days=90)),
    )


class TestMaskIban:
    def test_none_returns_none(self) -> None:
        assert mask_iban(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert mask_iban("") is None

    def test_preserves_last_four_characters(self) -> None:
        iban = "NO9386011117947"
        result = mask_iban(iban)
        assert result is not None
        assert result.replace(" ", "").endswith(iban[-4:])

    def test_hides_every_character_before_the_last_four(self) -> None:
        iban = "NO9386011117947"
        result = mask_iban(iban)
        assert result is not None
        masked_prefix = result.replace(" ", "")[:-4]
        original_prefix = iban[:-4]
        assert len(masked_prefix) == len(original_prefix)
        assert all(char == "*" for char in masked_prefix)
        assert masked_prefix != original_prefix

    def test_removes_spaces_before_masking(self) -> None:
        assert mask_iban("NO93 8601 1117 947") == mask_iban("NO9386011117947")

    def test_output_is_grouped(self) -> None:
        result = mask_iban("NO9386011117947")
        assert result is not None
        assert " " in result

    def test_string_no_longer_than_tail_is_returned_unmasked(self) -> None:
        # Nothing to hide when the whole value already fits in the "tail" —
        # real IBANs are always far longer than 4 characters in practice.
        assert mask_iban("abcd") == "abcd"


class TestMintJwt:
    def test_produces_rs256_jwt_with_expected_claims(self) -> None:
        private_pem, public_pem = _generate_key_pair()
        app = AppCredential(application_id="app-123", private_key_pem=private_pem)

        token = mint_jwt(app)

        header = jwt.get_unverified_header(token)
        assert header["kid"] == "app-123"
        assert header["alg"] == "RS256"

        payload = jwt.decode(
            token, public_pem, algorithms=["RS256"], audience="api.enablebanking.com"
        )
        assert payload["iss"] == "enablebanking.com"
        assert payload["aud"] == "api.enablebanking.com"
        assert payload["exp"] - payload["iat"] == 3600

    def test_private_key_never_appears_in_the_token(self) -> None:
        private_pem, _ = _generate_key_pair()
        app = AppCredential(application_id="app-123", private_key_pem=private_pem)

        token = mint_jwt(app)

        assert private_pem not in token


class TestBankCredentialStore:
    def test_app_credential_round_trip(self, mocker: MockerFixture) -> None:
        _, set_password, get_password = _fake_keyring_backend()
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.set_password", side_effect=set_password
        )
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.get_password", side_effect=get_password
        )

        credential = AppCredential(application_id="app-123", private_key_pem="fake-pem")
        cred_store = BankCredentialStore()
        cred_store.put_app_credential(credential)

        assert cred_store.get_app_credential() == credential

    def test_get_app_credential_raises_when_missing(self, mocker: MockerFixture) -> None:
        mocker.patch("jb_gateway_mcp.credentials_bank.keyring.get_password", return_value=None)

        cred_store = BankCredentialStore()
        with pytest.raises(BankCredentialNotFoundError):
            cred_store.get_app_credential()

    def test_session_round_trip(self, mocker: MockerFixture) -> None:
        _, set_password, get_password = _fake_keyring_backend()
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.set_password", side_effect=set_password
        )
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.get_password", side_effect=get_password
        )

        session = _make_session()
        cred_store = BankCredentialStore()
        cred_store.put_session(session)

        assert cred_store.get_session("dnb") == session

    def test_get_session_raises_when_missing(self, mocker: MockerFixture) -> None:
        mocker.patch("jb_gateway_mcp.credentials_bank.keyring.get_password", return_value=None)

        cred_store = BankCredentialStore()
        with pytest.raises(BankCredentialNotFoundError):
            cred_store.get_session("dnb")

    def test_get_valid_session_returns_unexpired_session(self, mocker: MockerFixture) -> None:
        _, set_password, get_password = _fake_keyring_backend()
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.set_password", side_effect=set_password
        )
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.get_password", side_effect=get_password
        )

        session = _make_session(valid_until=datetime.now(UTC) + timedelta(days=1))
        cred_store = BankCredentialStore()
        cred_store.put_session(session)

        assert cred_store.get_valid_session("dnb") == session

    def test_get_valid_session_raises_needs_reconsent_when_expired(
        self, mocker: MockerFixture
    ) -> None:
        _, set_password, get_password = _fake_keyring_backend()
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.set_password", side_effect=set_password
        )
        mocker.patch(
            "jb_gateway_mcp.credentials_bank.keyring.get_password", side_effect=get_password
        )

        session = _make_session(valid_until=datetime.now(UTC) - timedelta(minutes=1))
        cred_store = BankCredentialStore()
        cred_store.put_session(session)

        with pytest.raises(NeedsReconsentError):
            cred_store.get_valid_session("dnb")


def test_bank_session_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BankSession(
            institution="dnb",
            session_id="s1",
            accounts=(),
            valid_until=datetime.now(),  # noqa: DTZ005 - intentionally naive for this test
        )
