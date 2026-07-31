"""Local cleanup CLI: revokes an onboarded account's Google OAuth grant and
removes its token from the OS keychain.

    uv run uninstall-google --account you@example.com

This only handles the two steps that are easy to forget (the token sitting
in your keychain, and the live grant on Google's side) — removing this
server from client configs and deleting the repo itself are still manual
steps, see README.md "Uninstalling".
"""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from urllib.parse import urlencode

from jb_gateway_mcp.credentials import CredentialNotFoundError, CredentialStore, TokenRecord

_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Revoke a Google account's grant and delete its stored token."
    )
    parser.add_argument(
        "--account", required=True, action="append", help="Account to remove (repeatable)"
    )
    parser.add_argument("--provider", default="google", help="Provider (default: google)")
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt for each account"
    )
    parser.add_argument(
        "--keep-remote-grant",
        action="store_true",
        help="Delete the local keychain entry only; don't revoke the grant on Google's side",
    )
    return parser.parse_args(argv)


def _revoke_remote_grant(record: TokenRecord) -> None:
    """Revoke the OAuth grant at Google's token revocation endpoint (RFC 7009).

    Raises on failure so the caller can decide whether to still proceed with
    local deletion. Only ever sends the token value itself to Google's own
    endpoint — never logs or prints it.
    """
    token = record.refresh_token or record.access_token
    data = urlencode({"token": token}).encode("ascii")
    request = urllib.request.Request(_REVOKE_URL, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"revoke endpoint returned status {response.status}")


def _uninstall_one(
    store: CredentialStore, provider: str, account: str, *, skip_prompt: bool, keep_remote: bool
) -> None:
    try:
        record = store.get_token(provider, account)
    except CredentialNotFoundError:
        print(f"  {account}: no stored credential — nothing to do")
        return

    if not skip_prompt:
        answer = input(f"  Revoke and delete stored access for {account}? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print(f"  {account}: skipped")
            return

    if not keep_remote and provider == "google":
        try:
            _revoke_remote_grant(record)
            print(f"  {account}: revoked grant on Google's side")
        except (urllib.error.URLError, RuntimeError) as exc:
            print(
                f"  {account}: WARNING — could not revoke the remote grant ({exc}). "
                "Revoke it manually at https://myaccount.google.com/permissions. "
                "Deleting the local keychain entry anyway."
            )

    store.delete_token(provider, account)
    print(f"  {account}: removed from keychain")


def main() -> None:
    args = _parse_args()
    store = CredentialStore()

    print(f"Cleaning up {len(args.account)} account(s) for provider={args.provider!r}:")
    for account in args.account:
        _uninstall_one(
            store,
            args.provider,
            account,
            skip_prompt=args.yes,
            keep_remote=args.keep_remote_grant,
        )

    print(
        "\nStill manual (see README.md 'Uninstalling'): remove the jb-gateway-mcp entry "
        "from any client configs, delete the audit log if you want it gone, and delete "
        "the project directory when you're done."
    )


if __name__ == "__main__":
    main()
