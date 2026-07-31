"""Token refresh logic for provider OAuth tokens (Google, v1 MVP).

Wraps `google-auth`'s refresh mechanism so no raw provider exception ever
crosses this module's boundary — callers only ever see `NeedsReconsentError`
(refresh token revoked/expired, human must re-onboard) or
`TokenRefreshError` (some other refresh failure, e.g. transient).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC
from typing import TYPE_CHECKING

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

if TYPE_CHECKING:
    from jb_gateway_mcp.credentials import TokenRecord

_SUPPORTED_PROVIDERS = {"google"}


class NeedsReconsentError(Exception):
    """Raised when a refresh token is no longer valid (revoked/expired).

    The account must go through the onboarding CLI again to re-consent.
    """


class TokenRefreshError(Exception):
    """Raised when a refresh attempt fails for a reason other than an
    invalid/revoked grant (e.g. a transient network or server error).
    """


def refresh_token(record: TokenRecord) -> TokenRecord:
    """Refresh `record`'s access token and return an updated `TokenRecord`."""
    if record.provider not in _SUPPORTED_PROVIDERS:
        raise TokenRefreshError(f"no refresh support for provider={record.provider!r}")

    # google-auth ships without inline type annotations, so these calls are
    # untyped from mypy's perspective even under --strict.
    oauth_credentials = Credentials(  # type: ignore[no-untyped-call]
        token=record.access_token,
        refresh_token=record.refresh_token,
        token_uri=record.token_uri,
        client_id=record.client_id,
        client_secret=record.client_secret,
    )

    try:
        oauth_credentials.refresh(Request())  # type: ignore[no-untyped-call]
    except RefreshError as exc:
        # google-auth surfaces a revoked/expired refresh token as an
        # "invalid_grant" error from Google's token endpoint, embedded in
        # the exception message (see google.oauth2._client._handle_error_response).
        if "invalid_grant" in str(exc):
            raise NeedsReconsentError(
                f"refresh token for provider={record.provider!r} account={record.account!r} "
                "is no longer valid; re-run onboarding for this account"
            ) from exc
        raise TokenRefreshError(
            f"token refresh failed for provider={record.provider!r} account={record.account!r}"
        ) from exc

    if oauth_credentials.token is None or oauth_credentials.expiry is None:
        raise TokenRefreshError(
            f"refresh for provider={record.provider!r} account={record.account!r} "
            "did not return a token/expiry"
        )

    # google-auth's Credentials.expiry is naive UTC (see
    # google.auth._helpers.utcnow); normalize to timezone-aware UTC.
    expires_at = oauth_credentials.expiry.replace(tzinfo=UTC)

    return dataclasses.replace(
        record,
        access_token=oauth_credentials.token,
        refresh_token=oauth_credentials.refresh_token or record.refresh_token,
        expires_at=expires_at,
    )
