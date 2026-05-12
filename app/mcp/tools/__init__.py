"""MCP tool registrations."""

from fastmcp import FastMCP

from . import (
    get_application,
    get_machine,
    list_applications,
    list_machine_metric_history,
    list_machine_metrics,
    list_machines,
)


def register_tools(mcp: FastMCP) -> None:
    """Register every read-only MCP tool."""

    for module in (
        list_applications,
        get_application,
        list_machines,
        get_machine,
        list_machine_metrics,
        list_machine_metric_history,
    ):
        module.register(mcp)


__all__ = ["register_tools"]
