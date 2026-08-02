"""Google Drive adapter: list files (read-only) and read text-like file content.

Content is only fetched for plain-text mimetypes and exportable Google Docs
formats (Docs/Sheets/Slides, exported as text). Other mimetypes (images,
binaries, etc.) return metadata only — we don't attempt to handle every
binary format.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from jb_gateway_mcp.adapters.base import ToolSpec, build_google_client
from jb_gateway_mcp.credentials import CredentialStore

_SERVICE = "drive"
_VERSION = "v3"
_LIST_FIELDS = "files(id, name, mimeType, modifiedTime)"
_GET_FIELDS = "id, name, mimeType, size"
# Google's export API rejects text/plain for Sheets (400 "requested conversion
# is not supported") — text/csv is the closest plain-text equivalent there,
# and only covers the first/active sheet tab, never the whole workbook.
_EXPORT_MIMETYPE_BY_SOURCE = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_MAX_CONTENT_CHARS = 20_000

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="drive.list_files",
        scope="drive.readonly",
        description="List Drive files matching a query.",
    ),
    ToolSpec(
        name="drive.read_file",
        scope="drive.readonly",
        description="Read metadata and text content of a Drive file.",
    ),
]


def list_files(
    store: CredentialStore, account: str, query: str = "", page_size: int = 20
) -> list[dict[str, Any]]:
    client = build_google_client(store, account, _SERVICE, _VERSION)
    response = (
        client.files().list(q=query or None, pageSize=page_size, fields=_LIST_FIELDS).execute()
    )
    files: list[dict[str, Any]] = response.get("files", []) or []
    return files


def _fetch_content(client: Any, file_id: str, mime_type: str) -> str | None:
    export_mimetype = _EXPORT_MIMETYPE_BY_SOURCE.get(mime_type)
    if export_mimetype is not None:
        raw = client.files().export(fileId=file_id, mimeType=export_mimetype).execute()
    elif mime_type.startswith("text/") or mime_type == "application/json":
        raw = client.files().get_media(fileId=file_id).execute()
    else:
        return None

    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return text[:_MAX_CONTENT_CHARS]


def read_file(store: CredentialStore, account: str, file_id: str) -> dict[str, Any]:
    client = build_google_client(store, account, _SERVICE, _VERSION)
    metadata: dict[str, Any] = client.files().get(fileId=file_id, fields=_GET_FIELDS).execute()
    content = _fetch_content(client, file_id, metadata.get("mimeType", ""))
    return {**metadata, "content": content}


def get_handlers(store: CredentialStore) -> dict[str, Callable[..., Any]]:
    return {
        "drive.list_files": partial(list_files, store),
        "drive.read_file": partial(read_file, store),
    }
