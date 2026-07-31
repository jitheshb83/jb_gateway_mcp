from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from jb_gateway_mcp.adapters import google_gmail
from jb_gateway_mcp.credentials import CredentialStore


def _fake_store() -> MagicMock:
    return MagicMock(spec=CredentialStore)


def _patch_client(mocker: MockerFixture) -> MagicMock:
    client = MagicMock()
    mocker.patch("jb_gateway_mcp.adapters.google_gmail.build_google_client", return_value=client)
    return client


def test_list_messages_returns_id_snippet_threadid(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}]
    }
    client.users.return_value.messages.return_value.get.return_value.execute.side_effect = [
        {"id": "m1", "threadId": "t1", "snippet": "hello"},
        {"id": "m2", "threadId": "t2", "snippet": "world"},
    ]

    result = google_gmail.list_messages(_fake_store(), "me@example.com", query="is:unread")

    assert result == [
        {"id": "m1", "threadId": "t1", "snippet": "hello"},
        {"id": "m2", "threadId": "t2", "snippet": "world"},
    ]


def test_list_messages_empty_result(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.users.return_value.messages.return_value.list.return_value.execute.return_value = {}

    result = google_gmail.list_messages(_fake_store(), "me@example.com")

    assert result == []


def test_read_message_extracts_subject_from_snippet_and_body(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    body_text = "Hello world, this is the message body."
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    payload: dict[str, Any] = {
        "mimeType": "multipart/alternative",
        "headers": [
            {"name": "Subject", "value": "Test subject"},
            {"name": "From", "value": "sender@example.com"},
        ],
        "parts": [{"mimeType": "text/plain", "body": {"data": encoded_body}}],
    }
    client.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Hello world",
        "payload": payload,
    }

    result = google_gmail.read_message(_fake_store(), "me@example.com", "m1")

    assert result == {
        "id": "m1",
        "threadId": "t1",
        "subject": "Test subject",
        "from": "sender@example.com",
        "snippet": "Hello world",
        "body": body_text,
    }


def test_read_message_missing_body_returns_none(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "",
        "payload": {"mimeType": "text/plain", "headers": [], "body": {}},
    }

    result = google_gmail.read_message(_fake_store(), "me@example.com", "m1")

    assert result["body"] is None


def test_send_message_happy_path(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "t9",
    }

    result = google_gmail.send_message(
        _fake_store(), "me@example.com", to="b@example.com", subject="Hi", body="text"
    )

    assert result == {"id": "sent-1", "threadId": "t9"}


def test_send_message_rejects_empty_to(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_gmail.build_google_client")

    with pytest.raises(ValueError, match="'to'"):
        google_gmail.send_message(_fake_store(), "me@example.com", to="", subject="Hi", body="x")

    build_mock.assert_not_called()


def test_send_message_rejects_empty_subject(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_gmail.build_google_client")

    with pytest.raises(ValueError, match="'subject'"):
        google_gmail.send_message(
            _fake_store(), "me@example.com", to="b@example.com", subject="   ", body="x"
        )

    build_mock.assert_not_called()


def test_send_message_rejects_empty_body(mocker: MockerFixture) -> None:
    build_mock = mocker.patch("jb_gateway_mcp.adapters.google_gmail.build_google_client")

    with pytest.raises(ValueError, match="'body'"):
        google_gmail.send_message(
            _fake_store(), "me@example.com", to="b@example.com", subject="Hi", body=""
        )

    build_mock.assert_not_called()


def test_get_handlers_covers_every_tool_spec() -> None:
    store = _fake_store()
    handlers = google_gmail.get_handlers(store)
    assert set(handlers) == {spec.name for spec in google_gmail.TOOLS}
