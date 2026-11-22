"""Provider intelligence orchestration, local Ollama lifecycle, and report analysis."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from . import catalog_storage
from .database import utcnow_naive


class LocalRuntimeController:
    """Safely reuse or start a local Ollama server; never own external processes."""

    def __init__(self, startup_timeout: float = 20.0, poll_interval: float = 0.4):
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self._lock = asyncio.Lock()
        self._owned_process: subprocess.Popen | None = None
        self._owned_endpoint: str | None = None

    @staticmethod
    def _is_loopback(base_url: str) -> bool:
        try:
            parsed = urlparse(base_url)
            if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
                return False
            parsed.port  # Validate malformed ports before attempting process startup.
        except ValueError:
            return False
        host = parsed.hostname.lower()
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _find_executable() -> str | None:
        executable = shutil.which("ollama")
        if executable:
            return executable
        candidates = []
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            program_files = os.environ.get("ProgramFiles", "C:/Program Files")
            if local_app_data:
                candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
            candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
        elif sys.platform == "darwin":
            candidates.extend([
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                Path("/usr/local/bin/ollama"),
            ])
        else:
            candidates.extend([Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")])
        return next((str(path) for path in candidates if path.is_file()), None)

    @staticmethod
    async def _probe(base_url: str, trust_env: bool = False) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.5, trust_env=trust_env) as client:
                response = await client.get(f"{base_url.rstrip('/')}/api/version")
                return response.is_success
        except (httpx.HTTPError, ValueError):
            return False

    async def ensure_running(self, base_url: str, auto_start: bool = True) -> dict[str, Any]:
        endpoint = base_url.rstrip("/")
        try:
            parsed_base = urlparse(endpoint)
            host = parsed_base.hostname or ""
            parsed_port = parsed_base.port
            is_local_host = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_local_host = False
            parsed_base = None
            parsed_port = None
        if parsed_base is not None and parsed_base.scheme == "http" and is_local_host and parsed_port is None:
            bind_host = "127.0.0.1" if host.lower() == "localhost" else host
            if ":" in bind_host:
                bind_host = f"[{bind_host}]"
            endpoint = parsed_base._replace(netloc=f"{bind_host}:11434").geturl().rstrip("/")
        elif parsed_base is not None and parsed_base.scheme == "http" and host.lower() == "localhost":
            endpoint = parsed_base._replace(netloc=f"127.0.0.1:{parsed_port}").geturl().rstrip("/")
        local_endpoint = self._is_loopback(endpoint)
        async with self._lock:
            probe_result = await self._probe(endpoint) if local_endpoint else await self._probe(endpoint, trust_env=True)
            if probe_result:
                return {
                    "status": "ready",
                    "endpoint_scope": "local" if local_endpoint else "remote",
                    "already_running": True,
                    "started_by_application": False,
                    "error": None,
                }

            if not local_endpoint:
                return {
                    "status": "unavailable",
                    "endpoint_scope": "remote",
                    "already_running": False,
                    "started_by_application": False,
                    "error": {"category": "remote_endpoint_unreachable", "message": "The configured remote Ollama endpoint did not respond; local startup was not attempted."},
                }

            if not auto_start:
                return {
                    "status": "unavailable",
                    "endpoint_scope": "local",
                    "already_running": False,
                    "started_by_application": False,
                    "error": {"category": "auto_start_disabled", "message": "Ollama is not responding. Start Ollama manually or enable automatic startup."},
                }

            if self._owned_process is not None and self._owned_process.poll() is None:
                if self._owned_endpoint != endpoint:
                    return {
                        "status": "unavailable",
                        "endpoint_scope": "local",
                        "already_running": False,
                        "started_by_application": False,
                        "error": {"category": "runtime_managed_for_different_endpoint", "message": "This application already manages an Ollama process for a different endpoint."},
                    }
                process = self._owned_process
            else:
                executable = self._find_executable()
                if not executable:
                    return {
                        "status": "not_installed",
                        "endpoint_scope": "local",
                        "already_running": False,
                        "started_by_application": False,
                        "error": {"category": "ollama_not_installed", "message": "The Ollama executable was not found. Install Ollama or add its CLI to PATH."},
                    }
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                parsed_endpoint = urlparse(endpoint)
                bind_host = parsed_endpoint.hostname or "127.0.0.1"
                if bind_host == "localhost":
                    bind_host = "127.0.0.1"
                if ":" in bind_host and not bind_host.startswith("["):
                    bind_host = f"[{bind_host}]"
                bind_port = parsed_endpoint.port or 11434
                child_environment = os.environ.copy()
                child_environment["OLLAMA_HOST"] = f"{bind_host}:{bind_port}"
                try:
                    process = subprocess.Popen(
                        [executable, "serve"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        shell=False,
                        close_fds=True,
                        creationflags=creation_flags,
                        env=child_environment,
                    )
                    self._owned_process = process
                    self._owned_endpoint = endpoint
                except OSError:
                    return {
                        "status": "error",
                        "endpoint_scope": "local",
                        "already_running": False,
                        "started_by_application": False,
                        "error": {"category": "startup_failed", "message": "The Ollama process could not be started. Check installation and operating-system permissions."},
                    }

            deadline = asyncio.get_running_loop().time() + self.startup_timeout
            while asyncio.get_running_loop().time() < deadline:
                if await self._probe(endpoint):
                    return {
                        "status": "ready",
                        "endpoint_scope": "local",
                        "already_running": False,
                        "started_by_application": process is self._owned_process,
                        "process_id": process.pid,
                        "error": None,
                    }
                if process.poll() is not None:
                    return {
                        "status": "error",
                        "endpoint_scope": "local",
                        "already_running": False,
                        "started_by_application": False,
                        "error": {"category": "process_exited", "message": "The Ollama process exited before its API became ready."},
                    }
                await asyncio.sleep(self.poll_interval)

            return {
                "status": "starting_timeout",
                "endpoint_scope": "local",
                "already_running": False,
                "started_by_application": process is self._owned_process,
                "process_id": process.pid,
                "error": {"category": "startup_timeout", "message": "Ollama did not become ready before the startup timeout."},
            }


TASK_TAXONOMY = (
    "general_chat", "coding", "reasoning", "summarization", "translation",
    "vision", "embeddings", "tool_calling",
)


def _model_task_assessments(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Assess model tasks only from model-level evidence, never provider-wide hints."""
    metadata = model.get("catalog_data") or {}
    profile = model.get("operator_profile") or {}
    curated_tasks = {str(task).lower() for task in (profile.get("tasks") or [])}
    raw_capabilities = metadata.get("capabilities") or []
    if isinstance(raw_capabilities, str):
        raw_capabilities = [raw_capabilities]
    capabilities = {str(item).lower() for item in raw_capabilities}
    capability_map = {
        "vision": {"vision"},
        "embeddings": {"embedding", "embeddings"},
        "tool_calling": {"tools", "tool_calling"},
        "reasoning": {"thinking", "reasoning"},
        "coding": {"coding", "code"},
    }
    assessments = []
    for task in TASK_TAXONOMY:
        direct = capability_map.get(task, set()).intersection(capabilities)
        if direct:
            status, evidence = "supported", "provider_reported"
        elif task == "general_chat" and "completion" in capabilities:
            status, evidence = "likely", "provider_reported"
        elif task in curated_tasks:
            status, evidence = "likely", "curated_manifest"
        else:
            status, evidence = "unknown", "unknown"
        assessments.append({
            "task": task,
            "suitability": status,
            "evidence": evidence,
            "confidence": "high" if status == "supported" else "medium" if status == "likely" else "none",
        })
    return assessments


def _analyze_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    analyzed_models = []
    for model in snapshot.get("live_models", []):
        if not model.get("active"):
            continue
        metadata = model.get("catalog_data") or {}
        details = metadata.get("details") or {}
        raw_capabilities = metadata.get("capabilities") or []
        if isinstance(raw_capabilities, str):
            raw_capabilities = [raw_capabilities]
        capabilities = {str(item).lower() for item in raw_capabilities}
        has_completion = "completion" in capabilities
        has_embeddings = bool({"embedding", "embeddings"}.intersection(capabilities))
        has_tools = bool({"tools", "tool_calling"}.intersection(capabilities))
        has_vision = "vision" in capabilities
        runtime_observation = metadata.get("runtime_observation") or {}
        runtime = model.get("runtime") or {}
        if has_embeddings and not has_completion:
            model_kind = "embedding"
        elif has_completion and has_vision:
            model_kind = "multimodal_generative"
        elif has_completion:
            model_kind = "generative"
        elif capabilities:
            model_kind = "specialized"
        else:
            model_kind = "unknown"
        roles = []
        if has_embeddings:
            roles.append("embedding_indexer")
        if has_completion:
            roles.append("conversation_candidate")
        if has_tools and has_completion:
            roles.append("tool_using_conversation")
        if has_vision:
            roles.append("vision_analyzer")
        assessments = _model_task_assessments(model)
        analyzed_models.append({
            "model_id": model["model_id"],
            "source": model.get("source"),
            "model_kind": model_kind,
            "model_roles": roles,
            "chat_eligible": True if has_completion else False if has_embeddings else None,
            "metadata": {
                "family": details.get("family"),
                "families": details.get("families"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "size": metadata.get("size"),
                "digest": metadata.get("digest"),
                "modified_at": metadata.get("modified_at"),
                "context_length": metadata.get("context_length"),
                "capabilities": metadata.get("capabilities", []),
                "runtime_observation": runtime_observation,
            },
            "runtime": {
                "installed": bool(model.get("active")),
                "loaded": runtime_observation.get("loaded"),
                "inference_status": runtime.get("availability", "unknown"),
                "last_successful_request": runtime.get("last_successful_request"),
            },
            "task_suitability": assessments,
            "metadata_status": "available" if metadata else "unknown",
            "last_seen_at": model.get("last_seen_at"),
        })
    return analyzed_models


def _report_fingerprint(report: dict[str, Any]) -> str:
    """Hash semantic report facts while excluding timestamps and volatile sync history."""
    runtime = report.get("provider_runtime") or {}
    startup = runtime.get("startup") or {}
    quota = report.get("quota") or {}
    stable = {
        "provider_id": report.get("provider_id"),
        "report_type": report.get("report_type"),
        "overall_status": report.get("overall_status"),
        "provider_runtime": {
            "status": runtime.get("status"),
            "probe": runtime.get("probe"),
            "error": runtime.get("error"),
            "startup": {
                key: startup.get(key)
                for key in ("status", "endpoint_scope", "already_running", "started_by_application", "error")
                if key in startup
            },
        },
        "models": [
            {
                "model_id": model.get("model_id"),
                "model_kind": model.get("model_kind"),
                "model_roles": model.get("model_roles"),
                "chat_eligible": model.get("chat_eligible"),
                "metadata": {
                    key: model.get("metadata", {}).get(key)
                    for key in (
                        "family", "families", "parameter_size", "quantization_level",
                        "size", "digest", "modified_at", "context_length", "capabilities",
                        "runtime_observation",
                    )
                },
                "runtime": model.get("runtime"),
                "task_suitability": model.get("task_suitability"),
                "metadata_status": model.get("metadata_status"),
            }
            for model in report.get("models", [])
        ],
        "quota": {
            "status": quota.get("status"),
            "source": quota.get("source"),
            "data": quota.get("data"),
        },
        "warnings": report.get("warnings", []),
        "metadata_errors": report.get("metadata_errors", []),
        "limitations": report.get("limitations", []),
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_offline_report(db, provider_id: str) -> dict[str, Any]:
    """Build a report from SQLite only. This function performs no network or process I/O."""
    snapshot = catalog_storage.get_provider_catalog_snapshot(db, provider_id)
    generated_at = utcnow_naive().isoformat()
    source_times = [
        snapshot.get("provider_runtime", {}).get("checked_at"),
        *[item.get("synced_at") for item in snapshot.get("sync_history", [])],
        snapshot.get("quota", {}).get("observed_at"),
    ]
    parsed_times = []
    for value in source_times:
        if value:
            try:
                observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                parsed_times.append(observed.astimezone(timezone.utc))
            except ValueError:
                continue
    latest_observation = max(parsed_times) if parsed_times else None
    source_snapshot_at = latest_observation.isoformat() if latest_observation else None
    age_seconds = None
    freshness = "unknown"
    if latest_observation:
        age_seconds = max(0, int((datetime.now(timezone.utc) - latest_observation).total_seconds()))
        freshness = "fresh" if age_seconds <= 86400 else "stale"

    provider_runtime = dict(snapshot.get("provider_runtime", {}))
    provider_runtime["startup"] = provider_runtime.pop("runtime_details", None)
    runtime_status = provider_runtime.get("status", "unknown")
    overall_status = (
        "unavailable"
        if runtime_status in {"unavailable", "unreachable"}
        else "degraded"
        if runtime_status == "degraded" or freshness == "stale"
        else "unknown"
        if runtime_status == "unknown"
        else "healthy"
    )
    models = _analyze_snapshot(snapshot)
    report = {
        "provider_id": provider_id,
        "report_type": "offline",
        "generated_at": generated_at,
        "source_snapshot_at": source_snapshot_at,
        "freshness": {"status": freshness, "age_seconds": age_seconds},
        "overall_status": overall_status,
        "summary": f"Offline snapshot: {len(models)} active models; source data freshness is {freshness}.",
        "provider_runtime": provider_runtime,
        "models": models,
        "quota": snapshot.get("quota", {}),
        "sync_history": snapshot.get("sync_history", []),
        "limitations": ["This report reflects the last persisted observations and does not verify current provider reachability."],
    }
    report["fingerprint"] = _report_fingerprint(report)
    return report


def build_runtime_report(db, provider_id: str, connection_result: dict[str, Any], metadata_errors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    snapshot = catalog_storage.get_provider_catalog_snapshot(db, provider_id)
    models = _analyze_snapshot(snapshot)
    status = connection_result.get("status", "unknown")
    errors = metadata_errors or []
    sync_status = (connection_result.get("catalog_sync") or {}).get("status")
    warnings = []
    if status != "reachable":
        warnings.append("Provider is unreachable; model records represent the last persisted inventory.")
    if errors:
        warnings.append("Some model metadata could not be refreshed; prior known metadata was retained where available.")
    if sync_status == "empty_response_preserved":
        warnings.append("The provider returned an empty inventory; the last-known-good model catalog was preserved.")
    overall_status = (
        "unavailable"
        if status != "reachable"
        else "degraded"
        if errors or sync_status not in {None, "success"}
        else "healthy"
    )
    runtime = dict(snapshot.get("provider_runtime", {}))
    runtime["startup"] = connection_result.get("runtime") or runtime.get("runtime_details")
    runtime.pop("runtime_details", None)
    report = {
        "provider_id": provider_id,
        "report_type": "runtime",
        "generated_at": utcnow_naive().isoformat(),
        "source_snapshot_at": runtime.get("checked_at"),
        "freshness": {"status": "fresh" if status == "reachable" else "unknown", "age_seconds": 0 if status == "reachable" else None},
        "overall_status": overall_status,
        "summary": f"{provider_id}: {status}; {len(models)} active models; {len(errors)} metadata errors.",
        "warnings": warnings,
        "provider_runtime": runtime,
        "models": models,
        "quota": snapshot.get("quota", {}),
        "metadata_errors": errors,
        "sync_history": snapshot.get("sync_history", []),
    }
    report["fingerprint"] = _report_fingerprint(report)
    return report



_LOCAL_RUNTIME_CONTROLLER = LocalRuntimeController()


async def refresh_provider_intelligence(db, interface_manager, provider_id: str, config_loader) -> dict[str, Any]:
    """Refresh one provider, persist observations, and save its runtime intelligence report."""
    runtime = None
    if provider_id == "ollama":
        config = config_loader() or {}
        provider_config = (config.get("providers_config") or {}).get("ollama", {})
        runtime = await _LOCAL_RUNTIME_CONTROLLER.ensure_running(
            provider_config.get("base_url", "http://localhost:11434"),
            auto_start=bool(provider_config.get("auto_start", True)),
        )
        if runtime.get("status") != "ready":
            connection = {
                "provider": provider_id,
                "status": "unreachable",
                "probe": "local_runtime",
                "model_count": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "error": runtime.get("error"),
                "runtime": runtime,
            }
        else:
            connection = await interface_manager.check_connection(provider_id)
            connection["runtime"] = runtime
    else:
        connection = await interface_manager.check_connection(provider_id)

    model_ids = connection.pop("models", [])
    catalog_storage.record_provider_runtime(db, provider_id, connection)
    metadata_errors: list[dict[str, str]] = []
    if connection.get("status") == "reachable":
        metadata_by_model: dict[str, dict[str, Any]] = {}
        if provider_id == "ollama" and model_ids:
            try:
                metadata_result = await interface_manager.get_model_metadata(provider_id, model_ids)
                metadata_by_model = metadata_result.get("models", {})
                metadata_errors = metadata_result.get("errors", [])
            except Exception:
                metadata_errors = [{"category": "metadata_unavailable"}]
        operator = interface_manager.get_provider_catalog(provider_id).get("operator", {})
        aliases = set(operator.get("router_aliases", []))
        exact_model_ids = [model_id for model_id in model_ids if model_id not in aliases]
        sync_result = catalog_storage.sync_live_models(
            db,
            provider_id,
            exact_model_ids,
            source="ollama_local_api" if provider_id == "ollama" else "provider_api",
            model_metadata=metadata_by_model,
        )
        connection["catalog_sync"] = sync_result
        if metadata_errors:
            connection["metadata_errors"] = metadata_errors
    else:
        catalog_storage.record_sync_failure(db, provider_id, connection.get("error") or {
            "category": "catalog_unavailable",
            "message": "Provider catalog discovery was unsuccessful.",
        })

    report = build_runtime_report(db, provider_id, connection, metadata_errors)
    catalog_storage.save_intelligence_report(db, report)
    connection["intelligence_report"] = report
    return connection


def create_offline_intelligence_report(db, provider_id: str) -> dict[str, Any]:
    report = build_offline_report(db, provider_id)
    catalog_storage.save_intelligence_report(db, report)
    return report
