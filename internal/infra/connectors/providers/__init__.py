"""Metric provider connectors."""

from .empty import EmptyMetricCollector
from .mock import MockMetricCollector

__all__ = ["EmptyMetricCollector", "MockMetricCollector"]
