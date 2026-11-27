"""Normalized execution strategies (WP-8.3). Models are invoked only through InterfaceManager."""
from .base import ExecutionRequest, ExecutionResult
from .offline import OfflineStrategy
from .online import OnlineStrategy
from .selector import select_execution_strategy

__all__ = ["ExecutionRequest", "ExecutionResult", "OnlineStrategy", "OfflineStrategy", "select_execution_strategy"]
