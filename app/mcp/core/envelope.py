"""Shared MCP tool response envelope helpers."""

from collections.abc import Awaitable, Callable
import logging
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from app.mcp.core.models import MCPEnvelope, MCPPagination
from app.mcp.core.product_api import ProductAPIError
from internal.infra.observability import observe_mcp_tool_call


logger = logging.getLogger(__name__)


async def envelope(
    success_message: str,
    load: Callable[[], Awaitable[dict[str, Any]]],
    *,
    tool_name: str,
    paginated: bool = False,
    data_model: type[BaseModel] | None = None,
) -> MCPEnvelope[Any]:
    """Wrap a downstream product API call in the common MCP response envelope."""
    started_at = perf_counter()
    status = "failed"
    try:
        payload = await load()
        pagination = _pagination(payload) if paginated else None
        raw_data = {"items": payload.get("items", []), "offset": payload.get("offset", 0)} if paginated else payload
        data = _coerce_data(raw_data, data_model)
        status = "success"
        return MCPEnvelope(
            status="success",
            message=success_message,
            data=data,
            pagination=pagination,
            error=None,
        )
    except ProductAPIError as exc:
        logger.info("MCP tool %s failed with downstream API error: %s", tool_name, exc)
        return MCPEnvelope(
            status="failed",
            message=_failure_message(success_message),
            data={},
            pagination=None,
            error=str(exc),
        )
    except Exception:
        logger.exception("MCP tool %s failed with an unexpected error", tool_name)
        return MCPEnvelope(
            status="failed",
            message=_failure_message(success_message),
            data={},
            pagination=None,
            error="tool execution failed",
        )
    finally:
        observe_mcp_tool_call(tool_name=tool_name, status=status, duration_seconds=perf_counter() - started_at)


def _pagination(payload: dict[str, Any]) -> MCPPagination:
    """Build the short MCP pagination block from an API paginated response."""
    return MCPPagination(
        cursor=None,
        page_size=int(payload.get("limit", 0)),
        total=int(payload.get("total", 0)),
    )


def _coerce_data(raw_data: dict[str, Any], data_model: type[BaseModel] | None) -> BaseModel | dict[str, Any]:
    """Validate tool data with a typed MCP data model when one is provided."""
    if data_model is None:
        return raw_data
    return data_model.model_validate(raw_data)


def _failure_message(success_message: str) -> str:
    """Derive the standard failed message from a short success message."""
    if success_message.endswith("ed."):
        return success_message.removesuffix("ed.") + " failed."
    return "Tool failed."


__all__ = ["envelope"]
