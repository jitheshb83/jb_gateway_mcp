"""Live smoke test for jb_gateway_mcp: spawns the real server via
scripts/start.sh and drives it with a real MCP ClientSession, exactly as
Claude Desktop/Code or any other MCP client would.

Run from the repo root:
    uv run python .claude/skills/run-jb-gateway-mcp/scripts/smoke_test.py

Exit code 0 means: the process started, the MCP handshake succeeded, tools
were discovered, ping round-tripped, and the audit log contains no
token/secret material. A denial on the Google tool calls is an EXPECTED
outcome unless policy.yaml grants them for the caller id used below — that's
the deny-by-default design working, not a failure of this script.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

REPO_ROOT = Path(__file__).resolve().parents[4]
START_SCRIPT = REPO_ROOT / "scripts" / "start.sh"

# Placeholder — real end-to-end testing against your own inbox/calendar/drive
# needs a real, already-onboarded account (see README.md). Don't put a real
# account email in this shared script; override it for a one-off manual run
# instead (copy the script, or pass a different value here locally).
ACCOUNT = "smoke-test@example.com"
CALLER_ID = "local"


def render(result: CallToolResult) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content, indent=2, default=str)[:800]
    if result.content:
        return result.content[0].text[:800]  # type: ignore[union-attr]
    return "(empty)"


async def main() -> int:
    if not START_SCRIPT.exists():
        print(f"error: {START_SCRIPT} not found", file=sys.stderr)
        return 1

    tmp_dir = Path(tempfile.mkdtemp(prefix="jb_gateway_mcp_smoketest_"))
    audit_path = tmp_dir / "audit.jsonl"
    params = StdioServerParameters(
        command=str(START_SCRIPT),
        args=[],
        env={"JB_GATEWAY_AUDIT_LOG": str(audit_path), "JB_GATEWAY_CALLER_ID": CALLER_ID},
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init_result = await session.initialize()
        print(f"[1] Handshake OK — server: {init_result.server_info.name}")

        tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        expected = {
            "ping",
            "gmail.list_messages",
            "gmail.read_message",
            "gmail.send_message",
            "calendar.list_events",
            "calendar.create_event",
            "drive.list_files",
            "drive.read_file",
        }
        missing = expected - set(names)
        print(f"[2] Discovered {len(names)} tools: {names}")
        if missing:
            print(f"    MISSING expected tools: {missing}", file=sys.stderr)
            return 1

        ping = await session.call_tool("ping", {})
        pong = ping.content[0].text  # type: ignore[union-attr]
        print(f"[3] ping -> {pong}")
        if pong != "pong":
            print("    UNEXPECTED ping response", file=sys.stderr)
            return 1

        print(
            f"[4] Calling Google tools as caller={CALLER_ID!r} "
            "(allow/deny depends on policy.yaml):"
        )
        for tool_name, args in [
            ("gmail.list_messages", {"account": ACCOUNT, "query": ""}),
            ("calendar.list_events", {"account": ACCOUNT}),
            ("drive.list_files", {"account": ACCOUNT}),
        ]:
            result = await session.call_tool(tool_name, args)
            if not result.is_error:
                status = "ALLOWED (succeeded)"
            elif "no grant for caller" in render(result):
                status = "POLICY DENIED"
            else:
                # e.g. no credential stored for the placeholder ACCOUNT — policy
                # allowed the call, it failed downstream. Still a valid, expected
                # outcome when ACCOUNT hasn't been onboarded.
                status = "ERRORED (not a policy denial)"
            print(f"    - {tool_name}: {status} -> {render(result)}")

    print(f"\n[5] Audit log: {audit_path}")
    audit_text = audit_path.read_text()
    print(audit_text)

    if "ya29." in audit_text or '"access_token"' in audit_text or '"refresh_token"' in audit_text:
        print("SECURITY FAILURE: token material found in audit log", file=sys.stderr)
        return 1

    print("[6] Audit log contains no token material. Smoke test PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
