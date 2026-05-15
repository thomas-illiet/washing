"""MCP tool registrations."""

from fastmcp import FastMCP

from . import (
    application_environments_list,
    application_get,
    application_list,
    application_optimizations_get,
    application_regions_list,
    application_search,
    application_stats_get,
    machine_get,
    machine_list,
    machine_search,
)


def register_tools(mcp: FastMCP) -> None:
    """Register every read-only MCP tool."""

    for module in (
        application_list,
        application_search,
        application_get,
        application_regions_list,
        application_environments_list,
        machine_list,
        machine_search,
        machine_get,
        application_stats_get,
        application_optimizations_get,
    ):
        module.register(mcp)


__all__ = ["register_tools"]
