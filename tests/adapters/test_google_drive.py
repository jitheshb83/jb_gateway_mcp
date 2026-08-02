from __future__ import annotations

from unittest.mock import MagicMock

from pytest_mock import MockerFixture

from jb_gateway_mcp.adapters import google_drive
from jb_gateway_mcp.credentials import CredentialStore


def _fake_store() -> MagicMock:
    return MagicMock(spec=CredentialStore)


def _patch_client(mocker: MockerFixture) -> MagicMock:
    client = MagicMock()
    mocker.patch("jb_gateway_mcp.adapters.google_drive.build_google_client", return_value=client)
    return client


def test_list_files_returns_files(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f1", "name": "a.txt", "mimeType": "text/plain"}]
    }

    result = google_drive.list_files(_fake_store(), "me@example.com", query="name contains 'a'")

    assert result == [{"id": "f1", "name": "a.txt", "mimeType": "text/plain"}]


def test_list_files_empty_result(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.files.return_value.list.return_value.execute.return_value = {}

    result = google_drive.list_files(_fake_store(), "me@example.com")

    assert result == []


def test_read_file_plain_text_fetches_content_via_get_media(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": "a.txt",
        "mimeType": "text/plain",
        "size": "11",
    }
    client.files.return_value.get_media.return_value.execute.return_value = b"hello world"

    result = google_drive.read_file(_fake_store(), "me@example.com", "f1")

    assert result["id"] == "f1"
    assert result["content"] == "hello world"
    client.files.return_value.get_media.assert_called_once_with(fileId="f1")


def test_read_file_google_doc_uses_export(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.files.return_value.get.return_value.execute.return_value = {
        "id": "f2",
        "name": "Doc",
        "mimeType": "application/vnd.google-apps.document",
    }
    client.files.return_value.export.return_value.execute.return_value = b"exported text"

    result = google_drive.read_file(_fake_store(), "me@example.com", "f2")

    assert result["content"] == "exported text"
    client.files.return_value.export.assert_called_once_with(fileId="f2", mimeType="text/plain")


def test_read_file_google_sheet_exports_as_csv_not_plain_text(mocker: MockerFixture) -> None:
    """Google's export API rejects text/plain for spreadsheets (400 error) —
    text/csv is the correct export mimetype, confirmed against Drive's docs.
    """
    client = _patch_client(mocker)
    client.files.return_value.get.return_value.execute.return_value = {
        "id": "f4",
        "name": "Loan Tracker",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    client.files.return_value.export.return_value.execute.return_value = b"a,b\n1,2"

    result = google_drive.read_file(_fake_store(), "me@example.com", "f4")

    assert result["content"] == "a,b\n1,2"
    client.files.return_value.export.assert_called_once_with(fileId="f4", mimeType="text/csv")


def test_read_file_unsupported_mimetype_returns_metadata_only(mocker: MockerFixture) -> None:
    client = _patch_client(mocker)
    client.files.return_value.get.return_value.execute.return_value = {
        "id": "f3",
        "name": "photo.png",
        "mimeType": "image/png",
    }

    result = google_drive.read_file(_fake_store(), "me@example.com", "f3")

    assert result["content"] is None
    client.files.return_value.get_media.assert_not_called()
    client.files.return_value.export.assert_not_called()


def test_get_handlers_covers_every_tool_spec() -> None:
    handlers = google_drive.get_handlers(_fake_store())
    assert set(handlers) == {spec.name for spec in google_drive.TOOLS}
