"""Read-only MCP resources describing the Metrics Collector surface."""

import json

from fastmcp import FastMCP

from app.mcp.core.shared import ReadOnlyResourceAnnotations


MCP_CATALOG = {
    "server": "Metrics Collector MCP",
    "mode": "read_only",
    "rules": [
        "Use only read-only tools for inventory, metrics, and optimization consultation.",
        "Do not create, update, delete, sync, enable, disable, or enqueue worker tasks through MCP.",
        "Forwarded authorization comes from the caller's Bearer token.",
    ],
    "units": {
        "cpu": "cores",
        "ram": "mb",
        "disk": "mb",
        "utilization": "percent",
    },
    "tools": {
        "applications": [
            "application_list",
            "application_search",
            "application_get",
            "application_regions_list",
            "application_environments_list",
            "application_stats_get",
            "application_optimizations_get",
        ],
        "machines": [
            "machine_list",
            "machine_search",
            "machine_get",
        ],
    },
    "filters": {
        "applications": ["query", "environment", "region", "platform_id", "offset", "page_size"],
        "machines": [
            "query",
            "hostname",
            "external_id",
            "application",
            "application_id",
            "application_name",
            "environment",
            "region",
            "platform_id",
            "offset",
            "page_size",
        ],
        "stats_windows_days": [7, 15, 30],
    },
}

OPTIMIZATION_REASON_CODES = {
    "global_statuses": ["ready", "partial", "error"],
    "global_actions": ["scale_up", "scale_down", "mixed", "keep", "insufficient_data", "unavailable"],
    "scope_statuses": [
        "ok",
        "missing_provider",
        "ambiguous_provider",
        "insufficient_data",
        "missing_current_capacity",
    ],
    "scope_actions": ["scale_up", "scale_down", "keep", "insufficient_data", "unavailable"],
    "reason_codes": {
        "pressure_high": "Observed utilization is above the upscale threshold.",
        "pressure_low": "Observed utilization is below the downscale threshold.",
        "pressure_normal": "Observed utilization is inside the normal band.",
        "within_hysteresis": "A computed target would not materially change the current allocation.",
        "limited_history": "At least one sample exists, but the rolling window is not complete.",
        "no_samples": "No metric samples are available for the requested scope.",
        "no_provider": "No enabled provider is available for the requested scope.",
        "ambiguous_provider": "More than one enabled provider could supply the same scope.",
        "missing_current_capacity": "The current machine flavor has no capacity for the requested scope.",
        "raised_to_min_cpu": "The CPU recommendation was raised to the configured minimum.",
        "raised_to_min_ram": "The RAM recommendation was raised to the configured minimum.",
        "above_max_cpu": "The computed CPU target exceeds the configured maximum.",
        "above_max_ram": "The computed RAM target exceeds the configured maximum.",
        "unavailable": "The optimization reason is unavailable.",
    },
}


def register_resources(mcp: FastMCP) -> None:
    """Register static read-only resources for MCP clients."""

    @mcp.resource(
        "metrics-collector://mcp/catalog",
        name="mcp_catalog",
        title="MCP Catalog",
        description="Read-only catalog of Metrics Collector MCP tools, rules, filters, and units.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"catalog", "read-only"},
    )
    def mcp_catalog() -> str:
        """Return the read-only MCP catalog."""

        return _json_resource(MCP_CATALOG)

    @mcp.resource(
        "metrics-collector://optimizations/reason-codes",
        name="optimization_reason_codes",
        title="Optimization Reason Codes",
        description="Optimization statuses, actions, scope statuses, and reason-code meanings.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"optimizations", "read-only"},
    )
    def optimization_reason_codes() -> str:
        """Return optimization reason-code metadata."""

        return _json_resource(OPTIMIZATION_REASON_CODES)


def _json_resource(payload: dict[str, object]) -> str:
    """Serialize a stable JSON resource response."""
    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = ["register_resources"]
