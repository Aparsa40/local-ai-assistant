"""Backend adapter contract."""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.engine import Engine

from ..config import StorageConfig


class StorageAdapter(Protocol):
    """Creates the SQLAlchemy engine for one supported backend."""

    def create_engine(self, config: StorageConfig) -> Engine:
        ...
