"""Versioned schema migration entry point."""
from .runner import CURRENT_SCHEMA_REVISION, run_migrations

__all__ = ["CURRENT_SCHEMA_REVISION", "run_migrations"]
