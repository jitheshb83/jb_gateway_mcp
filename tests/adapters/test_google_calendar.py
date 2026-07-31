from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.adapters import google_calendar
from jb_gateway_mcp.credentials import CredentialStore


def _fake_store() -> MagicMock:
    return MagicMock(spec=CredentialStore)


def _patch_client(mocker: MockerFixture) -> MagicMock:
    client = MagicMock()
    mocker.patch(
        "jb_gateway_mcp.adapters.google_calendar.build_google_client", return_value=client
    )
    return client


def test_list_events_returns_trimmed_events(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "e1",
                "summary": "Standup",
                "start": {"dateTime": "2026-08-01T10:00:00+00:00"},
                "end": {"dateTime": "2026-08-01T10:30:00+00:00"},
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/e1",
                "creator": {"email": "someone@example.com"},
            }
        ]
    }

    result = google_calendar.list_events(_fake_store(), "me@example.com")

    assert result == [
        {
            "id": "e1",
            "summary": "Standup",
            "start": {"dateTime": "2026-08-01T10:00:00+00:00"},
            "end": {"dateTime": "2026-08-01T10:30:00+00:00"},
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/e1",
        }
    ]


def test_list_events_empty_result(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.events.return_value.list.return_value.execute.return_value = {}

    result = google_calendar.list_events(_fake_store(), "me@example.com")

    assert result == []


def test_create_event_happy_path(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.events.return_value.insert.return_value.execute.return_value = {
        "id": "e2",
        "summary": "New event",
        "start": {"dateTime": "2026-08-01T10:00:00+00:00"},
        "end": {"dateTime": "2026-08-01T11:00:00+00:00"},
        "status": "confirmed",
        "htmlLink": "https://calendar.google.com/e2",
    }

    result = google_calendar.create_event(
        _fake_store(),
        "me@example.com",
        calendar_id="primary",
        summary="New event",
        start_iso="2026-08-01T10:00:00+00:00",
        end_iso="2026-08-01T11:00:00+00:00",
    )

    assert result["id"] == "e2"
    assert result["summary"] == "New event"


def test_create_event_rejects_invalid_start_iso(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_calendar.build_google_client")

    with pytest.raises(ValueError, match="ISO-8601"):
        google_calendar.create_event(
            _fake_store(),
            "me@example.com",
            calendar_id="primary",
            summary="s",
            start_iso="not-a-date",
            end_iso="2026-08-01T11:00:00+00:00",
        )

    build_mock.assert_not_called()


def test_create_event_rejects_invalid_end_iso(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_calendar.build_google_client")

    with pytest.raises(ValueError, match="ISO-8601"):
        google_calendar.create_event(
            _fake_store(),
            "me@example.com",
            calendar_id="primary",
            summary="s",
            start_iso="2026-08-01T10:00:00+00:00",
            end_iso="not-a-date",
        )

    build_mock.assert_not_called()


def test_create_event_rejects_empty_summary(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_calendar.build_google_client")

    with pytest.raises(ValueError, match="'summary'"):
        google_calendar.create_event(
            _fake_store(),
            "me@example.com",
            calendar_id="primary",
            summary="  ",
            start_iso="2026-08-01T10:00:00+00:00",
            end_iso="2026-08-01T11:00:00+00:00",
        )

    build_mock.assert_not_called()


def test_get_handlers_covers_every_tool_spec() -> None:
    handlers = google_calendar.get_handlers(_fake_store())
    assert set(handlers) == {spec.name for spec in google_calendar.TOOLS}
