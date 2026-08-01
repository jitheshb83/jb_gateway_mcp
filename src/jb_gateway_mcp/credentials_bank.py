"""Keyring-backed credential store for Enable Banking (bank account data).

Unlike `credentials.py`'s OAuth-refresh-shaped `TokenRecord`, Enable Banking
uses a static per-application RSA private key — JWTs are minted locally per
request, there's no client-secret/refresh-token network round trip — plus a
per-institution, SCA-backed consent session that cannot be silently renewed.

Nothing in this module ever logs or raises an exception containing the
private key, a minted JWT, a session id, or a raw (unmasked) IBAN.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import jwt
import keyring

_APP_SERVICE = "jb_gateway_mcp:enablebanking_app"
_APP_ACCOUNT = "_app"
_SESSION_SERVICE = "jb_gateway_mcp:enablebanking_session"

_JWT_ISSUER = "enablebanking.com"
_JWT_AUDIENCE = "api.enablebanking.com"
_JWT_TTL_SECONDS = 3600


class BankCredentialNotFoundError(Exception):
    """Raised when no Enable Banking app credential or institution session is stored."""


class NeedsReconsentError(Exception):
    """Raised when a bank consent session has passed its `valid_until`.

    SCA-backed consent cannot be silently renewed — the human must re-run
    `onboard-bank --institution <name>`.
    """


@dataclass(frozen=True)
class AppCredential:
    """The one static, per-installation Enable Banking application identity."""

    application_id: str
    private_key_pem: str


@dataclass(frozen=True)
class BankAccount:
    """One linked account. `masked_iban` only — the raw IBAN is never stored."""

    uid: str
    masked_iban: str | None
    name: str
    currency: str


@dataclass(frozen=True)
class BankSession:
    """One institution's SCA consent grant and the accounts it covers."""

    institution: str
    session_id: str
    accounts: tuple[BankAccount, ...]
    valid_until: datetime

    def __post_init__(self) -> None:
        if self.valid_until.tzinfo is None:
            raise ValueError("valid_until must be timezone-aware (UTC)")


def mask_iban(iban: str | None) -> str | None:
    """Mask all but the last 4 characters of an IBAN, grouped like an IBAN.

    Applied to every IBAN this codebase ever touches — the account holder's
    own IBAN and, in transaction data, the counterparty's IBAN too. The raw
    value is never returned by any tool or persisted anywhere.
    """
    if not iban:
        return None
    cleaned = iban.replace(" ", "")
    tail = cleaned[-4:] if len(cleaned) > 4 else cleaned
    masked = "*" * max(len(cleaned) - len(tail), 0) + tail
    return " ".join(masked[i : i + 4] for i in range(0, len(masked), 4))


def mint_jwt(app: AppCredential) -> str:
    """Sign a short-lived RS256 JWT locally from the stored private key.

    No network call — Enable Banking's app-level auth needs no refresh
    token/token endpoint, unlike Google or GoCardless.
    """
    now = int(time.time())
    payload = {
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "iat": now,
        "exp": now + _JWT_TTL_SECONDS,
    }
    return jwt.encode(
        payload,
        app.private_key_pem,
        algorithm="RS256",
        headers={"kid": app.application_id},
    )


def _serialize_session(session: BankSession) -> str:
    payload = {
        "institution": session.institution,
        "session_id": session.session_id,
        "accounts": [asdict(account) for account in session.accounts],
        "valid_until": session.valid_until.astimezone(UTC).isoformat(),
    }
    return json.dumps(payload)


def _deserialize_session(raw: str) -> BankSession:
    payload = json.loads(raw)
    return BankSession(
        institution=payload["institution"],
        session_id=payload["session_id"],
        accounts=tuple(BankAccount(**account) for account in payload["accounts"]),
        valid_until=datetime.fromisoformat(payload["valid_until"]),
    )


class BankCredentialStore:
    """Reads/writes the Enable Banking app credential and per-institution sessions."""

    def put_app_credential(self, credential: AppCredential) -> None:
        keyring.set_password(_APP_SERVICE, _APP_ACCOUNT, json.dumps(asdict(credential)))

    def get_app_credential(self) -> AppCredential:
        raw = keyring.get_password(_APP_SERVICE, _APP_ACCOUNT)
        if raw is None:
            raise BankCredentialNotFoundError(
                "no Enable Banking application credential stored; run onboard-bank"
            )
        return AppCredential(**json.loads(raw))

    def put_session(self, session: BankSession) -> None:
        keyring.set_password(_SESSION_SERVICE, session.institution, _serialize_session(session))

    def get_session(self, institution: str) -> BankSession:
        raw = keyring.get_password(_SESSION_SERVICE, institution)
        if raw is None:
            raise BankCredentialNotFoundError(
                f"no bank consent stored for institution={institution!r}; "
                f"run: uv run onboard-bank --institution {institution}"
            )
        return _deserialize_session(raw)

    def get_valid_session(self, institution: str) -> BankSession:
        """Return the session for `institution` if its consent hasn't expired.

        There is no refresh path for a bank consent (SCA-backed, human must
        re-authenticate at the bank) — this only ever validates freshness,
        it never renews.
        """
        session = self.get_session(institution)
        if datetime.now(UTC) >= session.valid_until:
            raise NeedsReconsentError(
                f"consent for institution={institution!r} expired at "
                f"{session.valid_until.isoformat()}; "
                f"re-run: uv run onboard-bank --institution {institution}"
            )
        return session
