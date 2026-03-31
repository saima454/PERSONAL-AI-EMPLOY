"""Allow running the email MCP server as ``python -m backend.mcp_servers``."""

from backend.mcp_servers.email_server import main

if __name__ == "__main__":
    main()
