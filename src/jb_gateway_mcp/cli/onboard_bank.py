"""One-time, human-run consent CLI for Enable Banking bank accounts (DNB, Nordea, Revolut).

The first run also registers the application's static credential — the
`application_id` and private key `.pem` downloaded once from the Enable
Banking Control Panel (see the `connect-bank-account` skill in the
jb_claude_pluggins `jb-finance-mcp-plugin`, or this repo's own README, for
the Control Panel steps, which can't be automated: they require a human
sign-in and a browser form). Every run performs the per-institution SCA
consent flow and stores the resulting session.

Enable Banking requires an `https://` redirect URL with no plain-http
localhost exception (unlike Google), so rather than run a local HTTPS
listener with a self-signed certificate for a one-time flow, this CLI has
the human paste back the (deliberately unreachable) redirect URL after
completing consent in the browser, and extracts the authorization `code`
from it.

    uv run onboard-bank --institution dnb \\
        --application-id <uuid> --private-key /path/to/key.pem

    uv run onboard-bank --institution nordea   # app credential already stored
"""

from __future__ import annotations

import argparse
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from jb_gateway_mcp.credentials_bank import (
    AppCredential,
    BankAccount,
    BankCredentialNotFoundError,
    BankCredentialStore,
    BankSession,
    mask_iban,
    mint_jwt,
)

_BASE_URL = "https://api.enablebanking.com"
_REDIRECT_URL = "https://localhost:8080/callback"
_ACCESS_VALID_DAYS = 90
_REQUEST_TIMEOUT_SECONDS = 30.0

# Institution alias -> (ISO country code, substring to match in the ASPSP name
# returned by GET /aspsps). Extend here as more banks/countries are needed.
_INSTITUTION_COUNTRY = {"dnb": "NO", "nordea": "NO", "revolut": "NO"}
_INSTITUTION_NAME_HINT = {"dnb": "dnb", "nordea": "nordea", "revolut": "revolut"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-time consent flow to link a bank account (DNB/Nordea/Revolut) via Enable Banking."
        )
    )
    parser.add_argument("--institution", required=True, choices=sorted(_INSTITUTION_COUNTRY))
    parser.add_argument(
        "--application-id", help="Enable Banking application ID (only needed on first run)"
    )
    parser.add_argument(
        "--private-key",
        type=Path,
        help="Path to the application's private key .pem (only needed on first run)",
    )
    return parser.parse_args(argv)


def _load_or_store_app_credential(
    store: BankCredentialStore, application_id: str | None, private_key_path: Path | None
) -> AppCredential:
    try:
        return store.get_app_credential()
    except BankCredentialNotFoundError:
        pass

    if application_id is None or private_key_path is None:
        raise SystemExit(
            "No Enable Banking application credential stored yet. First run requires "
            "both --application-id and --private-key (from the Control Panel)."
        )

    credential = AppCredential(
        application_id=application_id,
        private_key_pem=private_key_path.read_text(),
    )
    store.put_app_credential(credential)
    return credential


def _resolve_aspsp(app: AppCredential, institution: str) -> dict[str, str]:
    country = _INSTITUTION_COUNTRY[institution]
    token = mint_jwt(app)
    response = httpx.get(
        f"{_BASE_URL}/aspsps",
        params={"country": country},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    aspsps = response.json().get("aspsps", [])

    hint = _INSTITUTION_NAME_HINT[institution]

    # Prefer an exact (case-insensitive) name match — e.g. plain "DNB" vs.
    # "DNB Corporate Mastercard", both of which contain the substring "dnb".
    exact_matches = [a for a in aspsps if a.get("name", "").lower() == hint]
    if len(exact_matches) == 1:
        return {"name": exact_matches[0]["name"], "country": country}

    matches = [a for a in aspsps if hint in a.get("name", "").lower()]
    if not matches:
        raise SystemExit(f"no ASPSP found for institution={institution!r} in country={country!r}")
    if len(matches) > 1:
        names = ", ".join(a["name"] for a in matches)
        raise SystemExit(
            f"multiple ASPSPs matched institution={institution!r}: {names} "
            "— narrow _INSTITUTION_NAME_HINT and retry"
        )
    return {"name": matches[0]["name"], "country": country}


def _start_authorization(app: AppCredential, aspsp: dict[str, str]) -> str:
    token = mint_jwt(app)
    valid_until = (datetime.now(UTC) + timedelta(days=_ACCESS_VALID_DAYS)).isoformat()
    body = {
        "access": {"valid_until": valid_until},
        "aspsp": aspsp,
        "state": "jb-gateway-mcp-onboarding",
        "redirect_url": _REDIRECT_URL,
        "psu_type": "personal",
    }
    response = httpx.post(
        f"{_BASE_URL}/auth",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    auth_url: str = response.json()["url"]
    return auth_url


def _prompt_for_code() -> str:
    pasted = input(
        "\nAfter completing the bank login, your browser will fail to load the "
        f"redirect page ({_REDIRECT_URL}) — that's expected, nothing is listening "
        "there. Copy the full URL from the address bar and paste it here:\n> "
    ).strip()
    query = parse_qs(urlparse(pasted).query)
    codes = query.get("code")
    if not codes:
        raise SystemExit("pasted URL did not contain a 'code' parameter")
    return codes[0]


def _exchange_code(app: AppCredential, code: str) -> dict[str, Any]:
    token = mint_jwt(app)
    response = httpx.post(
        f"{_BASE_URL}/sessions",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _build_session(institution: str, session_payload: dict[str, Any]) -> BankSession:
    accounts = tuple(
        BankAccount(
            uid=account["uid"],
            masked_iban=mask_iban(account.get("account_id", {}).get("iban")),
            name=account.get("name", ""),
            currency=account.get("currency", ""),
        )
        for account in session_payload.get("accounts", [])
    )

    valid_until_raw = session_payload.get("access", {}).get("valid_until")
    if valid_until_raw:
        valid_until = datetime.fromisoformat(valid_until_raw)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=UTC)
    else:
        valid_until = datetime.now(UTC) + timedelta(days=_ACCESS_VALID_DAYS)

    return BankSession(
        institution=institution,
        session_id=session_payload["session_id"],
        accounts=accounts,
        valid_until=valid_until,
    )


def main() -> None:
    args = _parse_args()
    store = BankCredentialStore()

    app = _load_or_store_app_credential(store, args.application_id, args.private_key)
    aspsp = _resolve_aspsp(app, args.institution)
    auth_url = _start_authorization(app, aspsp)

    print(f"\nOpen this URL and complete login at {aspsp['name']}:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    code = _prompt_for_code()
    session_payload = _exchange_code(app, code)
    session = _build_session(args.institution, session_payload)
    store.put_session(session)

    # Never print the private key, JWT, session id, or a raw (unmasked) IBAN.
    print(
        f"\n{args.institution} onboarded: {len(session.accounts)} account(s) linked, "
        f"consent valid until {session.valid_until.date().isoformat()}"
    )


if __name__ == "__main__":
    main()
