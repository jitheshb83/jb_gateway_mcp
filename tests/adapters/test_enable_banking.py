from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.adapters import enable_banking
from jb_gateway_mcp.credentials_bank import BankAccount, BankCredentialStore, BankSession

FAKE_JWT = "fake.jwt.do-not-leak"  # noqa: S105

_RAW_TRANSACTIONS = {
    "transactions": [
        {
            "transaction_amount": {"amount": "250.00", "currency": "NOK"},
            "credit_debit_indicator": "DBTR",
            "booking_date": "2026-07-15",
            "creditor": {"name": "Some Merchant AS"},
            "creditor_account": {"iban": "NO9386011117947"},
            "remittance_information": ["Invoice 4471"],
        },
        {
            "transaction_amount": {"amount": "5000.00", "currency": "NOK"},
            "credit_debit_indicator": "CRDT",
            "booking_date": "2026-07-01",
            "debtor": {"name": "Employer AS"},
            "debtor_account": {"iban": "NO1234567890123"},
            "remittance_information": ["Salary"],
        },
    ]
}


def _make_session(uid: str = "acc-1") -> BankSession:
    return BankSession(
        institution="dnb",
        session_id="session-do-not-leak",
        accounts=(BankAccount(uid=uid, masked_iban="**** 6538", name="Checking", currency="NOK"),),
        valid_until=datetime.now(UTC) + timedelta(days=30),
    )


def _fake_store(session: BankSession | None = None) -> MagicMock:
    store = MagicMock(spec=BankCredentialStore)
    store.get_valid_session.return_value = session or _make_session()
    store.get_app_credential.return_value = MagicMock()
    return store


def _patch_http(mocker: MockerFixture, json_response: dict[str, Any]) -> MagicMock:
    mocker.patch("jb_gateway_mcp.adapters.enable_banking.mint_jwt", return_value=FAKE_JWT)
    response = MagicMock()
    response.json.return_value = json_response
    response.raise_for_status.return_value = None
    return mocker.patch("jb_gateway_mcp.adapters.enable_banking.httpx.get", return_value=response)


def test_list_accounts_uses_stored_session_no_live_call(mocker: MockerFixture) -> None:
    get_mock = mocker.patch("jb_gateway_mcp.adapters.enable_banking.httpx.get")
    store = _fake_store()

    result = enable_banking.list_accounts(store, "dnb")

    assert result == [
        {
            "uid": "acc-1",
            "institution": "dnb",
            "name": "Checking",
            "currency": "NOK",
            "iban": "**** 6538",
        }
    ]
    get_mock.assert_not_called()


def test_get_balance_transforms_fields(mocker: MockerFixture) -> None:
    _patch_http(
        mocker,
        {
            "balances": [
                {
                    "balance_amount": {"amount": "100.50", "currency": "NOK"},
                    "balance_type": "CLAV",
                    "reference_date": "2026-08-01",
                }
            ]
        },
    )
    store = _fake_store()

    result = enable_banking.get_balance(store, "dnb", "acc-1")

    assert result == [
        {"amount": "100.50", "currency": "NOK", "type": "CLAV", "reference_date": "2026-08-01"}
    ]


def test_get_balance_rejects_account_uid_outside_consent(mocker: MockerFixture) -> None:
    get_mock = mocker.patch("jb_gateway_mcp.adapters.enable_banking.httpx.get")
    store = _fake_store()

    with pytest.raises(ValueError, match="not part of"):
        enable_banking.get_balance(store, "dnb", "someone-elses-account")

    get_mock.assert_not_called()


def test_summarize_spending_computes_totals_with_no_pii(mocker: MockerFixture) -> None:
    _patch_http(mocker, _RAW_TRANSACTIONS)
    store = _fake_store()

    result = enable_banking.summarize_spending(store, "dnb", "acc-1", "2026-07-01", "2026-07-31")

    assert result == {
        "currency": "NOK",
        "total_in": 5000.00,
        "total_out": 250.00,
        "net": 4750.00,
        "transaction_count": 2,
    }
    serialized = str(result)
    assert "Some Merchant" not in serialized
    assert "Employer" not in serialized
    assert "NO9386011117947" not in serialized


def test_list_transactions_summary_excludes_counterparty_and_description(
    mocker: MockerFixture,
) -> None:
    _patch_http(mocker, _RAW_TRANSACTIONS)
    store = _fake_store()

    result = enable_banking.list_transactions_summary(
        store, "dnb", "acc-1", "2026-07-01", "2026-07-31"
    )

    assert result == [
        {"date": "2026-07-15", "amount": "250.00", "currency": "NOK", "direction": "DBTR"},
        {"date": "2026-07-01", "amount": "5000.00", "currency": "NOK", "direction": "CRDT"},
    ]
    serialized = str(result)
    for leaked in ("Some Merchant", "Employer", "Invoice", "Salary", "NO93", "NO12"):
        assert leaked not in serialized


def test_list_transactions_detailed_includes_counterparty_but_masks_iban(
    mocker: MockerFixture,
) -> None:
    _patch_http(mocker, _RAW_TRANSACTIONS)
    store = _fake_store()

    result = enable_banking.list_transactions_detailed(
        store, "dnb", "acc-1", "2026-07-01", "2026-07-31"
    )

    assert result[0]["counterparty_name"] == "Some Merchant AS"
    assert result[0]["description"] == "Invoice 4471"
    assert result[1]["counterparty_name"] == "Employer AS"

    serialized = str(result)
    assert "NO9386011117947" not in serialized
    assert "NO1234567890123" not in serialized
    for transaction in result:
        iban = transaction["counterparty_iban"]
        assert iban is None or "*" in iban


def test_pagination_stops_when_no_continuation_key(mocker: MockerFixture) -> None:
    mocker.patch("jb_gateway_mcp.adapters.enable_banking.mint_jwt", return_value=FAKE_JWT)
    response = MagicMock()
    response.json.return_value = {
        "transactions": [
            {
                "transaction_amount": {"amount": "1", "currency": "NOK"},
                "credit_debit_indicator": "CRDT",
                "booking_date": "d",
            }
        ]
    }
    response.raise_for_status.return_value = None
    get_mock = mocker.patch(
        "jb_gateway_mcp.adapters.enable_banking.httpx.get", return_value=response
    )
    store = _fake_store()

    enable_banking.list_transactions_summary(store, "dnb", "acc-1", "2026-07-01", "2026-07-31")

    get_mock.assert_called_once()


def test_pagination_via_continuation_key_is_bounded(mocker: MockerFixture) -> None:
    mocker.patch("jb_gateway_mcp.adapters.enable_banking.mint_jwt", return_value=FAKE_JWT)

    def make_response() -> MagicMock:
        response = MagicMock()
        response.json.return_value = {
            "transactions": [
                {
                    "transaction_amount": {"amount": "1", "currency": "NOK"},
                    "credit_debit_indicator": "CRDT",
                    "booking_date": "d",
                }
            ],
            # Always present -> pagination must be bounded, not infinite.
            "continuation_key": "next-page",
        }
        response.raise_for_status.return_value = None
        return response

    get_mock = mocker.patch(
        "jb_gateway_mcp.adapters.enable_banking.httpx.get",
        side_effect=lambda *a, **k: make_response(),
    )
    store = _fake_store()

    result = enable_banking.list_transactions_summary(
        store, "dnb", "acc-1", "2026-07-01", "2026-07-31"
    )

    assert get_mock.call_count == enable_banking._MAX_TRANSACTION_PAGES
    assert len(result) == enable_banking._MAX_TRANSACTION_PAGES


def test_get_handlers_covers_every_tool_spec() -> None:
    store = _fake_store()
    handlers = enable_banking.get_handlers(store)
    assert set(handlers) == {spec.name for spec in enable_banking.TOOLS}


def test_no_write_endpoint_referenced_in_adapter_source() -> None:
    """Belt-and-suspenders: this adapter must never call Enable Banking's
    Payment Initiation endpoint. Enforced at the source-code level, not just
    by convention, since the underlying API does support it.
    """
    source = inspect.getsource(enable_banking)
    assert "/payments" not in source
    assert "httpx.post" not in source
    assert "httpx.put" not in source
    assert "httpx.delete" not in source
