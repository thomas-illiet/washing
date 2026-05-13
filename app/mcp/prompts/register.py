"""Reusable prompts for assistant workflows."""

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register reusable assistant prompts."""

    @mcp.prompt(
        name="discover_application",
        title="Discover Application",
        description="Guide the assistant through discovering an application and its machines.",
        tags={"applications", "discovery"},
    )
    def discover_application(application_hint: str | None = None) -> str:
        """Create an application discovery workflow prompt."""

        hint = f" Start with this hint: {application_hint}." if application_hint else ""
        return (
            "Help the user discover an application in Metrics Collector."
            f"{hint} Use discover_catalog to learn valid dimensions, then find_application or "
            "list_applications to identify candidates. If there are multiple matches, present the "
            "environment and region choices. Once a candidate is selected, use get_application_overview "
            "and summarize machines, platforms, and available current optimizations."
        )

    @mcp.prompt(
        name="explain_application_optimizations",
        title="Explain Application Optimizations",
        description="Guide the assistant through explaining current recommendations for one application.",
        tags={"applications", "optimizations"},
    )
    def explain_application_optimizations(application_name: str, environment: str | None = None, region: str | None = None) -> str:
        """Create an application optimization explanation prompt."""

        filters = [f"name={application_name}"]
        if environment:
            filters.append(f"environment={environment}")
        if region:
            filters.append(f"region={region}")
        return (
            "Explain optimization recommendations for an application. Find the application using "
            f"{', '.join(filters)}, call get_application_overview, and group recommendations by action "
            "and status. Highlight machines needing scale_up or scale_down first, then partial or error "
            "recommendations that need provider or metric attention. Avoid inventing missing metrics."
        )

    @mcp.prompt(
        name="investigate_machine_capacity",
        title="Investigate Machine Capacity",
        description="Guide the assistant through investigating one machine's capacity recommendation.",
        tags={"machines", "optimizations"},
    )
    def investigate_machine_capacity(machine_hint: str) -> str:
        """Create a machine capacity investigation prompt."""

        return (
            f"Investigate machine capacity for: {machine_hint}. Use find_machine to identify the machine. "
            "If there are multiple candidates, ask the user to choose by hostname, application, environment, "
            "region, or platform. Then call get_machine_context and explain_machine_optimization. Explain "
            "CPU, RAM, and disk separately using current capacity, recommended capacity, utilization, and reason."
        )


__all__ = ["register_prompts"]
