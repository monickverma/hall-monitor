"""Entry script for the Hall Monitor MCP server (stdio), launched by Bob from .bob/mcp.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hallmonitor.mcp_server import serve  # noqa: E402

serve()
