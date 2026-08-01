"""Enable Banking adapter: read-only account data for linked bank accounts.

Architecturally restricted to GET — `_get()` is the only HTTP verb this
module implements, and there is no `_post`/`_put`/`_delete` helper anywhere
in this file. Enable Banking's API also exposes a Payment Initiation
product, whose create-payment endpoint is never called or referenced here;
`tests/adapters/test_enable_banking.py` asserts this module's source
contains no reference to that endpoint's path as a belt-and-suspenders check
on top of just not writing it.

Tiered disclosure, enforced by tool identity (via `policy.yaml`), not by a
runtime parameter: `list_transactions_summary`/`summarize_spending` never
include counterparty name or payment description, even though the upstream
API returns them. Only `list_transactions_detailed` — a separate tool with
its own, off-by-default policy scope — includes that detail. Every IBAN
field, including the counterparty's IBAN inside detailed transactions, is
masked via `credentials_bank.mask_iban` before it leaves this module.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import httpx

from jb_gateway_mcp.adapters.base import ToolSpec
from jb_gateway_mcp.credentials_bank import BankCredentialStore, BankSession, mask_iban, mint_jwt

_BASE_URL = "https://api.enablebanking.com"
_REQUEST_TIMEOUT_SECONDS = 30.0
_MAX_TRANSACTION_PAGES = 5

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="bank.list_accounts",
        scope="bank.readonly",
        description="List linked bank accounts for an institution (masked IBAN).",
    ),
    ToolSpec(
        name="bank.get_balance",
        scope="bank.readonly",
        description="Get current/available balances for a bank account.",
    ),
    ToolSpec(
        name="bank.summarize_spending",
        scope="bank.readonly",
        description=(
            "Aggregate total in/out/net spending and transaction count for a date "
            "range. No counterparty names or descriptions are ever included."
        ),
    ),
    ToolSpec(
        name="bank.list_transactions_summary",
        scope="bank.readonly",
        description=(
            "List transactions for a date range: date, amount, currency only "
            "— no counterparty name or description."
        ),
    ),
    ToolSpec(
        name="bank.list_transactions_detailed",
        scope="bank.transactions.detailed",
        description=(
            "List transactions including counterparty name and payment description "
            "(IBANs still masked). Requires a separate, explicit policy.yaml grant "
            "— not enabled by default."
        ),
    ),
]


def _ensure_account_belongs(session: BankSession, account_uid: str) -> None:
    if account_uid not in {account.uid for account in session.accounts}:
        raise ValueError(
            f"account_uid {account_uid!r} is not part of the {session.institution!r} consent"
        )


def _get(app: Any, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = mint_jwt(app)
    response = httpx.get(
        f"{_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _fetch_all_transactions(
    app: Any, account_uid: str, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    params: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
    for _ in range(_MAX_TRANSACTION_PAGES):
        response = _get(app, f"/accounts/{account_uid}/transactions", params=params)
        transactions.extend(response.get("transactions", []) or [])
        continuation_key = response.get("continuation_key")
        if not continuation_key:
            break
        params = {"continuation_key": continuation_key}
    return transactions


def list_accounts(store: BankCredentialStore, institution: str) -> list[dict[str, Any]]:
    session = store.get_valid_session(institution)
    return [
        {
            "uid": account.uid,
            "institution": institution,
            "name": account.name,
            "currency": account.currency,
            "iban": account.masked_iban,
        }
        for account in session.accounts
    ]


def get_balance(
    store: BankCredentialStore, institution: str, account_uid: str
) -> list[dict[str, Any]]:
    session = store.get_valid_session(institution)
    _ensure_account_belongs(session, account_uid)
    app = store.get_app_credential()

    response = _get(app, f"/accounts/{account_uid}/balances")
    balances = response.get("balances", []) or []
    return [
        {
            "amount": balance.get("balance_amount", {}).get("amount"),
            "currency": balance.get("balance_amount", {}).get("currency"),
            "type": balance.get("balance_type"),
            "reference_date": balance.get("reference_date"),
        }
        for balance in balances
    ]


def summarize_spending(
    store: BankCredentialStore, institution: str, account_uid: str, date_from: str, date_to: str
) -> dict[str, Any]:
    session = store.get_valid_session(institution)
    _ensure_account_belongs(session, account_uid)
    app = store.get_app_credential()

    transactions = _fetch_all_transactions(app, account_uid, date_from, date_to)

    total_in = 0.0
    total_out = 0.0
    currency: str | None = None
    for transaction in transactions:
        amount_info = transaction.get("transaction_amount", {})
        amount = float(amount_info.get("amount") or 0)
        currency = currency or amount_info.get("currency")
        if transaction.get("credit_debit_indicator") == "CRDT":
            total_in += amount
        else:
            total_out += amount

    return {
        "currency": currency,
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net": round(total_in - total_out, 2),
        "transaction_count": len(transactions),
    }


def list_transactions_summary(
    store: BankCredentialStore, institution: str, account_uid: str, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    session = store.get_valid_session(institution)
    _ensure_account_belongs(session, account_uid)
    app = store.get_app_credential()

    transactions = _fetch_all_transactions(app, account_uid, date_from, date_to)
    return [
        {
            "date": transaction.get("booking_date") or transaction.get("transaction_date"),
            "amount": transaction.get("transaction_amount", {}).get("amount"),
            "currency": transaction.get("transaction_amount", {}).get("currency"),
            "direction": transaction.get("credit_debit_indicator"),
        }
        for transaction in transactions
    ]


def list_transactions_detailed(
    store: BankCredentialStore, institution: str, account_uid: str, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    session = store.get_valid_session(institution)
    _ensure_account_belongs(session, account_uid)
    app = store.get_app_credential()

    transactions = _fetch_all_transactions(app, account_uid, date_from, date_to)
    results: list[dict[str, Any]] = []
    for transaction in transactions:
        is_credit = transaction.get("credit_debit_indicator") == "CRDT"
        counterparty = transaction.get("debtor") if is_credit else transaction.get("creditor")
        counterparty_account = (
            transaction.get("debtor_account") if is_credit else transaction.get("creditor_account")
        )
        remittance = transaction.get("remittance_information") or []
        results.append(
            {
                "date": transaction.get("booking_date") or transaction.get("transaction_date"),
                "amount": transaction.get("transaction_amount", {}).get("amount"),
                "currency": transaction.get("transaction_amount", {}).get("currency"),
                "direction": transaction.get("credit_debit_indicator"),
                "counterparty_name": (counterparty or {}).get("name"),
                "counterparty_iban": mask_iban((counterparty_account or {}).get("iban")),
                "description": " ".join(remittance) if remittance else None,
            }
        )
    return results


def get_handlers(store: BankCredentialStore) -> dict[str, Callable[..., Any]]:
    return {
        "bank.list_accounts": partial(list_accounts, store),
        "bank.get_balance": partial(get_balance, store),
        "bank.summarize_spending": partial(summarize_spending, store),
        "bank.list_transactions_summary": partial(list_transactions_summary, store),
        "bank.list_transactions_detailed": partial(list_transactions_detailed, store),
    }
