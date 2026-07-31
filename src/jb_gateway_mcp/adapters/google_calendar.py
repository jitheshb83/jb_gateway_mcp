"""Google Calendar adapter: list events (read-only) and create events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any

from jb_gateway_mcp.adapters.base import ToolSpec, build_google_client
from jb_gateway_mcp.credentials import CredentialStore

_SERVICE = "calendar"
_VERSION = "v3"

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="calendar.list_events",
        scope="calendar.readonly",
        description="List upcoming events on a calendar.",
    ),
    ToolSpec(
        name="calendar.create_event",
        scope="calendar.events",
        description="Create a new calendar event.",
    ),
]


def _trim_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "status": event.get("status"),
        "htmlLink": event.get("htmlLink"),
    }


def list_events(
    store: CredentialStore, account: str, calendar_id: str = "primary", max_results: int = 10
) -> list[dict[str, Any]]:
    client = build_google_client(store, account, _SERVICE, _VERSION)
    response = (
        client.events()
        .list(
            calendarId=calendar_id,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    items: list[dict[str, Any]] = response.get("items", []) or []
    return [_trim_event(event) for event in items]


def create_event(
    store: CredentialStore,
    account: str,
    calendar_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
) -> dict[str, Any]:
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("'summary' must be a non-empty string")
    try:
        datetime.fromisoformat(start_iso)
        datetime.fromisoformat(end_iso)
    except ValueError as exc:
        raise ValueError(f"start_iso/end_iso must be ISO-8601 datetimes: {exc}") from exc

    client = build_google_client(store, account, _SERVICE, _VERSION)
    body = {"summary": summary, "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}}
    event = client.events().insert(calendarId=calendar_id, body=body).execute()
    return _trim_event(event)


def get_handlers(store: CredentialStore) -> dict[str, Callable[..., Any]]:
    return {
        "calendar.list_events": partial(list_events, store),
        "calendar.create_event": partial(create_event, store),
    }
