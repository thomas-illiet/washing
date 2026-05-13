"""MCP tool registrations."""

from fastmcp import FastMCP

from . import discovery


def register_tools(mcp: FastMCP) -> None:
    """Register every read-only MCP tool."""

    for module in (discovery,):
        module.register(mcp)


__all__ = ["register_tools"]
