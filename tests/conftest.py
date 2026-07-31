"""Keep `jb_gateway_mcp.server`'s module-level side effects (audit log dir
creation) out of the real user home directory during test runs.

This must run before `jb_gateway_mcp.server` is first imported by any test
module, so it lives at conftest module level rather than inside a fixture.
"""

import os
import tempfile
from pathlib import Path

_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="jb_gateway_mcp_test_"))
os.environ.setdefault("JB_GATEWAY_AUDIT_LOG", str(_TEST_STATE_DIR / "audit.jsonl"))
