"""Deterministic workflows backed by existing application services.

The registry is intentionally explicit: only workflows registered by the
application composition root can execute. Workflow handlers receive no user-
supplied callable or destination and operate through existing service facades.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    description: str
    handler: Callable[[], str]


class WorkflowRegistry:
    """Small allow-listed registry for deterministic application workflows."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}

    def register(self, name: str, description: str, handler: Callable[[], str]) -> None:
        normalized = str(name).strip()
        if not normalized or len(normalized) > 80 or not normalized.replace("_", "").isalnum():
            raise ValueError("workflow name must be a short alphanumeric identifier")
        if normalized in self._workflows:
            raise ValueError("workflow is already registered")
        if not callable(handler):
            raise TypeError("workflow handler must be callable")
        self._workflows[normalized] = WorkflowDefinition(normalized, str(description)[:200], handler)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._workflows))

    def describe(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"name": item.name, "description": item.description}
            for item in sorted(self._workflows.values(), key=lambda value: value.name)
        )

    def execute(self, name: str) -> str:
        definition = self._workflows.get(str(name))
        if definition is None:
            raise LookupError("workflow is not registered")
        result = definition.handler()
        if not isinstance(result, str) or not result.strip():
            raise ValueError("workflow returned no usable result")
        return result.strip()[:12000]


def build_default_workflow_registry(session_factory: Callable[[], object]) -> WorkflowRegistry:
    """Register read-only workflows implemented by existing project services."""
    from core.catalog_storage import get_operational_report

    registry = WorkflowRegistry()

    def provider_operational_report() -> str:
        # Reuse the existing catalog service facade and caller-owned DB session.
        with session_factory() as db:
            report = get_operational_report(db)

        providers = report.get("providers", []) if isinstance(report, dict) else []
        lines = [
            "گزارش عملیاتی سرویس‌ها و Providerها",
            f"زمان تولید گزارش: {report.get('generated_at', 'نامشخص')}",
            f"تعداد Providerهای ثبت‌شده: {len(providers)}",
        ]
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            runtime = provider.get("provider_runtime") or {}
            live_models = provider.get("live_models") or []
            active_models = sum(
                1 for model in live_models
                if isinstance(model, dict) and model.get("active") is True
            )
            name = (provider.get("operator") or {}).get("name") or provider.get("provider_id", "unknown")
            lines.append(
                f"- {name}: وضعیت Runtime={runtime.get('status', 'unknown')}، "
                f"مدل‌های فعال={active_models} از {len(live_models)}"
            )
        if not providers:
            lines.append("در حال حاضر Provider ثبت‌شده‌ای در کاتالوگ عملیاتی وجود ندارد.")
        lines.append("این گزارش فقط وضعیت ذخیره‌شده در کاتالوگ را نمایش می‌دهد و Probe زنده اجرا نمی‌کند.")
        return "\n".join(lines)

    registry.register(
        "provider_operational_report",
        "گزارش فقط‌خواندنی وضعیت Providerها، Runtime و تعداد مدل‌های فعال از کاتالوگ عملیاتی",
        provider_operational_report,
    )
    return registry
