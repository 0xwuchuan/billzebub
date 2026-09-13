"""Console entry point for the local Billzebub MCP stdio adapter."""

from __future__ import annotations

import sys

from billzebub.agent_mcp import McpConfigurationError, run_stdio


def main() -> int:
    try:
        return run_stdio()
    except McpConfigurationError:
        print("Billzebub MCP configuration is invalid.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
