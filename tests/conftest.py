"""Keep `jb_gateway_mcp.server`'s module-level side effects (audit log dir
creation, policy file load) out of the real user home directory during test
runs.

This must run before `jb_gateway_mcp.server` is first imported by any test
module, so it lives at conftest module level rather than inside a fixture.
"""

import os
import tempfile
from pathlib import Path

_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="jb_gateway_mcp_test_"))
os.environ.setdefault("JB_GATEWAY_AUDIT_LOG", str(_TEST_STATE_DIR / "audit.jsonl"))

# JB_GATEWAY_POLICY_FILE defaults to ~/.jb_gateway_mcp/policy.yaml, which may
# not exist on the machine running the tests — point module-level imports at
# the repo's own tracked policy.yaml instead of depending on that.
os.environ.setdefault(
    "JB_GATEWAY_POLICY_FILE", str(Path(__file__).resolve().parent.parent / "policy.yaml")
)
