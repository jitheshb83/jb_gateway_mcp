"""Gmail adapter: list/read messages (read-only) and send messages."""

from __future__ import annotations

import base64
from collections.abc import Callable
from email.mime.text import MIMEText
from functools import partial
from typing import Any

from jb_gateway_mcp.adapters.base import ToolSpec, build_google_client
from jb_gateway_mcp.credentials import CredentialStore

_SERVICE = "gmail"
_VERSION = "v1"
_MAX_BODY_CHARS = 20_000

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="gmail.list_messages",
        scope="gmail.readonly",
        description="List Gmail messages for an account, optionally filtered by query.",
    ),
    ToolSpec(
        name="gmail.read_message",
        scope="gmail.readonly",
        description="Read a single Gmail message's subject/from/snippet/body.",
    ),
    ToolSpec(
        name="gmail.send_message",
        scope="gmail.send",
        description="Send an email from an account.",
    ),
]


def _extract_header(headers: list[dict[str, str]], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def _decode_b64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body(payload: dict[str, Any]) -> str | None:
    """Find the first text/plain part in a (possibly nested multipart) payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_b64url(data)

    for part in payload.get("parts") or []:
        found = _extract_body(part)
        if found:
            return found
    return None


def list_messages(store: CredentialStore, account: str, query: str = "") -> list[dict[str, Any]]:
    client = build_google_client(store, account, _SERVICE, _VERSION)
    response = client.users().messages().list(userId="me", q=query or None).execute()
    refs: list[dict[str, Any]] = response.get("messages", []) or []

    results: list[dict[str, Any]] = []
    for ref in refs:
        # list() doesn't return snippets; fetch minimal detail per message for it.
        detail = (
            client.users()
            .messages()
            .get(userId="me", id=ref["id"], format="minimal")
            .execute()
        )
        results.append(
            {
                "id": detail.get("id"),
                "threadId": detail.get("threadId"),
                "snippet": detail.get("snippet", ""),
            }
        )
    return results


def read_message(store: CredentialStore, account: str, message_id: str) -> dict[str, Any]:
    client = build_google_client(store, account, _SERVICE, _VERSION)
    msg: dict[str, Any] = (
        client.users().messages().get(userId="me", id=message_id, format="full").execute()
    )
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    body = _extract_body(payload)

    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "subject": _extract_header(headers, "Subject"),
        "from": _extract_header(headers, "From"),
        "snippet": msg.get("snippet", ""),
        "body": body[:_MAX_BODY_CHARS] if body else None,
    }


def send_message(
    store: CredentialStore, account: str, to: str, subject: str, body: str
) -> dict[str, Any]:
    if not isinstance(to, str) or not to.strip():
        raise ValueError("'to' must be a non-empty string")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("'subject' must be a non-empty string")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("'body' must be a non-empty string")

    mime_message = MIMEText(body)
    mime_message["to"] = to
    mime_message["subject"] = subject
    raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")

    client = build_google_client(store, account, _SERVICE, _VERSION)
    result = client.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"id": result.get("id"), "threadId": result.get("threadId")}


def get_handlers(store: CredentialStore) -> dict[str, Callable[..., Any]]:
    return {
        "gmail.list_messages": partial(list_messages, store),
        "gmail.read_message": partial(read_message, store),
        "gmail.send_message": partial(send_message, store),
    }
