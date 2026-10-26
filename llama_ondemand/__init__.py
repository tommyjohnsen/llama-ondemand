# PROVENANCE
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex (gpt-5.6-sol, codex-cli 0.154.0) | 2026-10-26 | session public8-fix-20261026 | provenance block added
# reviewed-by: claude-code | 2026-10-26 | APPROVE | sha256:f36792e3fbc2c873e9dbeb67b3e4e793b39c03ff0e42fe37c9bd63cc90274668 | record public8-fix-20261026/llama-ondemand/r1/claude-code (Claude Code 2.1.287)
# END PROVENANCE
"""Start llama.cpp's llama-server on demand, locally or on a remote host over ssh, and stop it when idle.

A server this tool did not start is reused but never stopped.
"""
from .client import ChatResult, ClientError, ContextTooLarge, LlamaClient
from .manager import LlamaManager, LlamaRefused, LlamaUnavailable

__all__ = ["ChatResult", "ClientError", "ContextTooLarge", "LlamaClient", "LlamaManager", "LlamaRefused",
           "LlamaUnavailable"]
__version__ = "0.1.0"
