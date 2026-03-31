"""MCP Servers — ACTION layer for the AI Employee system.

This package contains Model Context Protocol servers that execute approved
actions on behalf of the user. Per constitution Principle II (Separation of
Concerns), MCP servers ONLY execute actions that have been approved through
the HITL workflow in vault/Approved/.

Servers communicate via stdio transport as defined by the MCP specification.
"""
