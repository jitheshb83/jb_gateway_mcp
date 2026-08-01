"""Shared building blocks for Google service adapters.

`googleapiclient` ships no type stubs/py.typed marker, so importing it is
treated as `Any` by mypy under strict mode — that's expected and confined to
this one import site.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from jb_gateway_mcp.credentials import CredentialStore


@dataclass(frozen=True)
class ToolSpec:
    """Describes one adapter tool: its name, required policy scope, and description.

    `cache_ttl_seconds`: opt-in, per-tool. None (the default) means never
    cached — every call reaches the handler. Only set this for read-only,
    idempotent tools where slightly-stale data is an acceptable trade for
    not re-hitting a scarce upstream quota (e.g. Enable Banking's daily,
    not short-term, per-consent access cap) — never for a write/send tool.
    """

    name: str
    scope: str
    description: str
    cache_ttl_seconds: float | None = None


def build_google_client(
    store: CredentialStore, account: str, service_name: str, version: str
) -> Resource:
    """Fetch a valid token for `account` and build an authenticated Google API client.

    The access token never leaves this call — callers get back a client object,
    never the token itself.
    """
    record = store.get_valid_token("google", account)
    credentials = Credentials(token=record.access_token)  # type: ignore[no-untyped-call]
    return build(service_name, version, credentials=credentials, cache_discovery=False)
