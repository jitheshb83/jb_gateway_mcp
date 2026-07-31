"""One-time, human-run OAuth onboarding CLI for a Google account.

Never invoked by an agent — a human runs this interactively to grant
consent once; the resulting token is stored in the OS keychain for
adapters to use via `CredentialStore.get_valid_token`.

    uv run onboard-google --account me@example.com \\
        --client-secrets /path/to/client_secret.json
"""

from __future__ import annotations

import argparse
from datetime import UTC
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from jb_gateway_mcp.credentials import CredentialStore, TokenRecord

# Read-only by default; write scopes (e.g. gmail.send) are opt-in via --scopes.
_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time OAuth consent flow to onboard a Google account for jb_gateway_mcp."
    )
    parser.add_argument("--account", required=True, help="Google account email being onboarded")
    parser.add_argument(
        "--client-secrets",
        required=True,
        type=Path,
        help="Path to the OAuth client secret JSON downloaded from Google Cloud Console",
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=_DEFAULT_SCOPES,
        help="Space-separated OAuth scopes to request (default: read-only Gmail/Calendar/Drive)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secrets), scopes=args.scopes
    )
    flow.run_local_server()
    oauth_credentials = flow.credentials

    if oauth_credentials.refresh_token is None or oauth_credentials.expiry is None:
        raise RuntimeError(
            "Google did not return a refresh token/expiry for this consent grant; "
            "try again (Google omits a refresh token on repeat consent for the same "
            "account/app unless re-prompted)"
        )

    record = TokenRecord(
        provider="google",
        account=args.account,
        access_token=oauth_credentials.token,
        refresh_token=oauth_credentials.refresh_token,
        expires_at=oauth_credentials.expiry.replace(tzinfo=UTC),
        client_id=oauth_credentials.client_id,
        client_secret=oauth_credentials.client_secret,
        token_uri=oauth_credentials.token_uri,
    )
    CredentialStore().put_token(record)

    # Never print/log token values — only the account and granted scopes.
    print(f"{args.account} onboarded, scopes: {sorted(args.scopes)}")


if __name__ == "__main__":
    main()
