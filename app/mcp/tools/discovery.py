"""Assistant-first MCP discovery tools."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import FetchResponse, MachineOptimizationExplanation, SearchResponse, SearchResult
from app.mcp.core.product_api import (
    discovery_application_overview,
    discovery_applications,
    discovery_current_optimizations,
    discovery_machine_context,
    discovery_machine_search,
    discovery_record,
    discovery_catalog as read_discovery_catalog,
)
from app.mcp.core.shared import DiscoveryLimit, OptionalPositiveInt, PositiveInt, ReadOnlyToolAnnotations
from internal.contracts.http.resources import (
    ApplicationOverviewRead,
    ApplicationSummaryRead,
    BoundedResponse,
    DiscoveryCatalogRead,
    DiscoveryRecordRead,
    MachineContextRead,
    MachineOptimizationAction,
    MachineOptimizationStatus,
    MachineRead,
    OptimizationRecommendationRead,
)


def register(mcp: FastMCP) -> None:
    """Register assistant-first read-only discovery tools."""

    @mcp.tool(
        name="discover_catalog",
        title="Discover Inventory Catalog",
        annotations=ReadOnlyToolAnnotations,
        tags={"discovery", "catalog"},
    )
    async def discover_catalog(ctx: Context) -> DiscoveryCatalogRead:
        """Discover available platforms, environments, regions, metric types, and optimization vocabulary."""

        return DiscoveryCatalogRead.model_validate(await read_discovery_catalog(ctx))

    @mcp.tool(
        name="list_applications",
        title="List Applications",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "discovery"},
    )
    async def list_applications(
        ctx: Context,
        name: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        platform_id: OptionalPositiveInt = None,
        max_results: DiscoveryLimit = 25,
    ) -> BoundedResponse[ApplicationSummaryRead]:
        """List application summaries with machine and current optimization counts; no pagination required."""

        payload = await discovery_applications(
            ctx,
            name=name,
            environment=environment,
            region=region,
            platform_id=platform_id,
            max_results=max_results,
        )
        return BoundedResponse[ApplicationSummaryRead].model_validate(payload)

    @mcp.tool(
        name="find_application",
        title="Find Application",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "search"},
    )
    async def find_application(
        ctx: Context,
        query: str,
        environment: str | None = None,
        region: str | None = None,
        platform_id: OptionalPositiveInt = None,
        max_results: DiscoveryLimit = 10,
    ) -> BoundedResponse[ApplicationSummaryRead]:
        """Find application projection rows by name plus optional environment, region, or platform filters."""

        payload = await discovery_applications(
            ctx,
            name=query,
            environment=environment,
            region=region,
            platform_id=platform_id,
            max_results=max_results,
        )
        return BoundedResponse[ApplicationSummaryRead].model_validate(payload)

    @mcp.tool(
        name="get_application_overview",
        title="Get Application Overview",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "optimizations"},
    )
    async def get_application_overview(
        ctx: Context,
        application_id: PositiveInt,
        max_machines: DiscoveryLimit = 25,
        max_optimizations: DiscoveryLimit = 25,
    ) -> ApplicationOverviewRead:
        """Get one application's machines and current optimization recommendations."""

        payload = await discovery_application_overview(
            ctx,
            application_id=application_id,
            max_machines=max_machines,
            max_optimizations=max_optimizations,
        )
        return ApplicationOverviewRead.model_validate(payload)

    @mcp.tool(
        name="list_application_machines",
        title="List Application Machines",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "machines"},
    )
    async def list_application_machines(
        ctx: Context,
        application_id: PositiveInt,
        max_results: DiscoveryLimit = 25,
    ) -> BoundedResponse[MachineRead]:
        """List machines belonging to one application projection row without pagination."""

        overview = ApplicationOverviewRead.model_validate(
            await discovery_application_overview(
                ctx,
                application_id=application_id,
                max_machines=max_results,
                max_optimizations=1,
            )
        )
        return overview.machines

    @mcp.tool(
        name="find_machine",
        title="Find Machine",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines", "search"},
    )
    async def find_machine(
        ctx: Context,
        query: str | None = None,
        hostname: str | None = None,
        external_id: str | None = None,
        application: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        platform_id: OptionalPositiveInt = None,
        max_results: DiscoveryLimit = 25,
    ) -> BoundedResponse[MachineRead]:
        """Find machines by hostname, external id, application, environment, region, or platform."""

        payload = await discovery_machine_search(
            ctx,
            q=query,
            hostname=hostname,
            external_id=external_id,
            application=application,
            environment=environment,
            region=region,
            platform_id=platform_id,
            max_results=max_results,
        )
        return BoundedResponse[MachineRead].model_validate(payload)

    @mcp.tool(
        name="get_machine_context",
        title="Get Machine Context",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines", "metrics", "optimizations"},
    )
    async def get_machine_context(ctx: Context, machine_id: PositiveInt) -> MachineContextRead:
        """Get one machine with platform, application, latest metrics, and current optimization context."""

        return MachineContextRead.model_validate(await discovery_machine_context(ctx, machine_id))

    @mcp.tool(
        name="list_current_optimizations",
        title="List Current Optimizations",
        annotations=ReadOnlyToolAnnotations,
        tags={"optimizations", "discovery"},
    )
    async def list_current_optimizations(
        ctx: Context,
        platform_id: OptionalPositiveInt = None,
        application: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        status: MachineOptimizationStatus | None = None,
        action: MachineOptimizationAction | None = None,
        max_results: DiscoveryLimit = 25,
    ) -> BoundedResponse[OptimizationRecommendationRead]:
        """List current machine optimization recommendations with machine ownership context."""

        payload = await discovery_current_optimizations(
            ctx,
            platform_id=platform_id,
            application=application,
            environment=environment,
            region=region,
            status=status,
            action=action,
            max_results=max_results,
        )
        return BoundedResponse[OptimizationRecommendationRead].model_validate(payload)

    @mcp.tool(
        name="explain_machine_optimization",
        title="Explain Machine Optimization",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines", "optimizations"},
    )
    async def explain_machine_optimization(ctx: Context, machine_id: PositiveInt) -> MachineOptimizationExplanation:
        """Explain the current optimization recommendation for one machine in deterministic terms."""

        context = MachineContextRead.model_validate(await discovery_machine_context(ctx, machine_id))
        optimization = context.current_optimization
        if optimization is None:
            return MachineOptimizationExplanation(
                machine_id=context.machine.id,
                hostname=context.machine.hostname,
                summary=f"{context.machine.hostname} has no current optimization recommendation yet.",
                context=context,
            )

        resource_parts = []
        for scope, resource in optimization.resources.items():
            current = "unknown" if resource.current is None else f"{resource.current:g} {resource.unit}"
            recommended = (
                "unavailable" if resource.recommended is None else f"{resource.recommended:g} {resource.unit}"
            )
            resource_parts.append(
                f"{scope}: {resource.action} from {current} to {recommended} ({resource.reason})"
            )
        summary = (
            f"{context.machine.hostname} current optimization is {optimization.action} "
            f"with status {optimization.status}. " + "; ".join(resource_parts)
        )
        return MachineOptimizationExplanation(
            machine_id=context.machine.id,
            hostname=context.machine.hostname,
            status=optimization.status,
            action=optimization.action,
            summary=summary,
            context=context,
        )

    @mcp.tool(
        name="search",
        title="Search Discovery Records",
        annotations=ReadOnlyToolAnnotations,
        tags={"search", "chatgpt"},
    )
    async def search(ctx: Context, query: str) -> SearchResponse:
        """Search applications, machines, and current optimizations. Returns ChatGPT-compatible result objects."""

        results: list[SearchResult] = []
        seen: set[str] = set()

        def add_result(record_id: str, title: str) -> None:
            if record_id in seen:
                return
            seen.add(record_id)
            results.append(SearchResult(id=record_id, title=title, url=f"metrics-collector://records/{record_id}"))

        if not query.strip():
            add_result("catalog", "Metrics Collector discovery catalog")
            return SearchResponse(results=results)

        applications = BoundedResponse[ApplicationSummaryRead].model_validate(
            await discovery_applications(ctx, name=query, max_results=5)
        )
        for item in applications.items:
            app = item.application
            add_result(
                f"application:{app.id}",
                f"Application {app.name} in {app.environment}/{app.region}",
            )

        machines = BoundedResponse[MachineRead].model_validate(
            await discovery_machine_search(ctx, q=query, max_results=10)
        )
        for machine in machines.items:
            title = f"Machine {machine.hostname}"
            if machine.application:
                title = f"{title} for {machine.application}"
            add_result(f"machine:{machine.id}", title)

        action = _optimization_action_from_query(query)
        status = _optimization_status_from_query(query)
        include_general_optimizations = any(
            word in query.lower()
            for word in ("optimization", "optimisation", "capacity", "scale", "resize", "recommendation")
        )
        optimization_application = None if include_general_optimizations or action or status else query
        optimizations = BoundedResponse[OptimizationRecommendationRead].model_validate(
            await discovery_current_optimizations(
                ctx,
                application=optimization_application,
                action=action,
                status=status,
                max_results=5,
            )
        )
        for item in optimizations.items:
            add_result(
                f"optimization:{item.optimization.id}",
                f"{item.machine.hostname} optimization: {item.optimization.action} ({item.optimization.status})",
            )

        if not results:
            add_result("catalog", "Metrics Collector discovery catalog")
        return SearchResponse(results=results)

    @mcp.tool(
        name="fetch",
        title="Fetch Discovery Record",
        annotations=ReadOnlyToolAnnotations,
        tags={"fetch", "chatgpt"},
    )
    async def fetch(ctx: Context, id: str) -> FetchResponse:
        """Fetch a full ChatGPT-compatible discovery record by id returned from search."""

        record = DiscoveryRecordRead.model_validate(await discovery_record(ctx, id))
        return FetchResponse(
            id=record.id,
            title=record.title,
            text=record.text,
            url=record.url,
            metadata=record.metadata,
        )


def _optimization_action_from_query(query: str) -> MachineOptimizationAction | None:
    """Infer an optimization action filter from natural search text."""
    normalized = query.lower().replace("-", " ").replace("_", " ")
    if "scale up" in normalized or "increase" in normalized:
        return "scale_up"
    if "scale down" in normalized or "decrease" in normalized or "downsize" in normalized:
        return "scale_down"
    if "mixed" in normalized:
        return "mixed"
    if "keep" in normalized:
        return "keep"
    if "insufficient" in normalized:
        return "insufficient_data"
    if "unavailable" in normalized:
        return "unavailable"
    return None


def _optimization_status_from_query(query: str) -> MachineOptimizationStatus | None:
    """Infer an optimization status filter from natural search text."""
    normalized = query.lower()
    if "ready" in normalized:
        return "ready"
    if "partial" in normalized:
        return "partial"
    if "error" in normalized or "ambiguous" in normalized:
        return "error"
    return None


__all__ = ["register"]
