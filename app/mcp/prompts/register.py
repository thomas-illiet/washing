"""Reusable MCP prompts for chat-first Metrics Collector workflows."""

from fastmcp import FastMCP

from app.mcp.core.shared import ApplicationId, MachineId, OptionalSearchQuery, StatsWindowDays


def register_prompts(mcp: FastMCP) -> None:
    """Register reusable prompt templates for MCP clients."""

    @mcp.prompt(
        name="application_capacity_review",
        title="Application Capacity Review",
        description="Guide an application-level capacity and optimization review.",
        tags={"applications", "metrics", "optimizations"},
    )
    def application_capacity_review(application_id: ApplicationId, window_days: StatsWindowDays = 7) -> str:
        """Review one application's capacity, utilization, and optimization recommendation."""

        return "\n".join(
            [
                "Review the application capacity posture with the Metrics Collector MCP tools.",
                f"1. Call application_get with application_id={application_id}.",
                f"2. Call application_stats_get with application_id={application_id} and window_days={window_days}.",
                f"3. Call application_optimizations_get with application_id={application_id}.",
                "Summarize allocated CPU/RAM/disk, utilization, current recommendation, confidence, and caveats.",
                "Do not suggest write, sync, enable, disable, or worker-task actions through MCP.",
            ]
        )

    @mcp.prompt(
        name="machine_optimization_explanation",
        title="Machine Optimization Explanation",
        description="Guide a machine-level recommendation explanation.",
        tags={"machines", "metrics", "optimizations"},
    )
    def machine_optimization_explanation(machine_id: MachineId) -> str:
        """Explain the latest metrics and current optimization for one machine."""

        return "\n".join(
            [
                "Explain the current optimization recommendation for one machine.",
                f"1. Call machine_get with machine_id={machine_id}.",
                "2. Compare current CPU/RAM/disk allocation with recommended values.",
                "3. Explain each resource reason code in plain language.",
                "Call out missing providers, ambiguous providers, or insufficient data when present.",
                "Do not suggest write, sync, enable, disable, or worker-task actions through MCP.",
            ]
        )

    @mcp.prompt(
        name="inventory_scope_discovery",
        title="Inventory Scope Discovery",
        description="Guide discovery of inventory scope before drilling into machines or applications.",
        tags={"applications", "machines", "search"},
    )
    def inventory_scope_discovery(search_term: OptionalSearchQuery = None) -> str:
        """Discover application and machine inventory scope for a user's question."""

        search_guidance = (
            f"Start with application_search and machine_search using query={search_term!r}."
            if search_term
            else "Start with application_list, application_regions_list, and application_environments_list."
        )
        return "\n".join(
            [
                "Discover the safest read-only inventory scope before answering.",
                search_guidance,
                "Use platform_id, environment, region, offset, and page_size filters to narrow broad result sets.",
                "Once the scope is clear, use application_get, machine_get, stats, or optimization tools as needed.",
                "Do not suggest write, sync, enable, disable, or worker-task actions through MCP.",
            ]
        )


__all__ = ["register_prompts"]
