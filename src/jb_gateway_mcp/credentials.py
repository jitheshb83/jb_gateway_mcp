"""Keyring-backed credential store for provider OAuth tokens.

Tokens are serialized to JSON and stored via the OS keychain (through the
`keyring` package). Nothing in this module ever logs or raises an exception
containing a token value — only provider/account identifiers are referenced
in error messages.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import keyring

from jb_gateway_mcp import token_lifecycle

_SERVICE_PREFIX = "jb_gateway_mcp"

# Refresh a little before actual expiry so an in-flight tool call doesn't
# race a token that expires between the freshness check and the API call.
_CLOCK_SKEW_BUFFER = timedelta(seconds=60)


class CredentialNotFoundError(Exception):
    """Raised when no credential is stored for a given provider/account."""


@dataclass(frozen=True)
class TokenRecord:
    """A stored OAuth token for one (provider, account) pair.

    `client_id`/`client_secret`/`token_uri` are the OAuth app's own token
    endpoint credentials (from the client secrets file used at onboarding).
    Google's refresh grant requires them alongside the refresh token, so
    they travel with the record rather than being looked up separately.
    """

    provider: str
    account: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    client_id: str
    client_secret: str
    token_uri: str

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware (UTC)")


def _service_name(provider: str) -> str:
    return f"{_SERVICE_PREFIX}:{provider}"


def _serialize(record: TokenRecord) -> str:
    payload = asdict(record)
    payload["expires_at"] = record.expires_at.astimezone(UTC).isoformat()
    return json.dumps(payload)


def _deserialize(raw: str) -> TokenRecord:
    payload = json.loads(raw)
    payload["expires_at"] = datetime.fromisoformat(payload["expires_at"])
    return TokenRecord(**payload)


class CredentialStore:
    """Reads/writes `TokenRecord`s via the OS keychain, refreshing as needed."""

    def put_token(self, record: TokenRecord) -> None:
        keyring.set_password(_service_name(record.provider), record.account, _serialize(record))

    def get_token(self, provider: str, account: str) -> TokenRecord:
        raw = keyring.get_password(_service_name(provider), account)
        if raw is None:
            raise CredentialNotFoundError(
                f"no credential stored for provider={provider!r} account={account!r}"
            )
        return _deserialize(raw)

    def get_valid_token(self, provider: str, account: str) -> TokenRecord:
        """Return a non-expired token, refreshing and persisting it if needed.

        This is the method adapters call — it never returns a stale token.
        """
        record = self.get_token(provider, account)
        if datetime.now(UTC) < record.expires_at - _CLOCK_SKEW_BUFFER:
            return record

        refreshed = token_lifecycle.refresh_token(record)
        self.put_token(refreshed)
        return refreshed
