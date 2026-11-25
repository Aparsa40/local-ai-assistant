"""Destination and egress authorization separate from retrieval (WP-8.3).

Retrieval authorization (PermissionManager, ContextManager scope checks) and
destination authorization are different decisions. Permission to read local
material never implies permission to transmit it to a cloud provider.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import DestinationClass

# Only the local Ollama adapter is a local destination today; every other
# registered adapter is a cloud destination.
LOCAL_PROVIDER_IDS = frozenset({"ollama"})

CLOUD_PROVIDER_IDS = frozenset({
    "openrouter", "google_ai_studio", "cloudflare_workers_ai", "groq", "cohere",
})


class EgressDeniedError(PermissionError):
    """Private context would be transmitted without explicit authorization."""


@dataclass(frozen=True)
class EgressDecision:
    destination_class: DestinationClass
    allowed: bool
    reason_code: str
    excluded_source_types: tuple[str, ...] = ()


def classify_destination(provider_id: str | None) -> DestinationClass:
    if not provider_id:
        return DestinationClass.NONE
    if provider_id in LOCAL_PROVIDER_IDS:
        return DestinationClass.LOCAL
    return DestinationClass.CLOUD


def authorize_transmission(
    provider_id: str | None,
    *,
    includes_private_context: bool,
    user_authorized_private_context: bool,
) -> EgressDecision:
    """Decide what may be transmitted to the destination.

    Conversation history and the user turn are the plain egress surface of an
    explicitly user-selected provider. Memory and knowledge scope items are
    private local context: they are stripped for cloud destinations unless the
    user explicitly authorized private-context egress for this request. The
    decision is fail-closed on any authorization ambiguity.
    """
    destination = classify_destination(provider_id)
    if destination is DestinationClass.LOCAL:
        return EgressDecision(destination, True, "local_destination")
    if not includes_private_context:
        return EgressDecision(destination, True, "conversation_content_only")
    if user_authorized_private_context:
        return EgressDecision(destination, True, "explicit_private_context_authorization")
    return EgressDecision(destination, False, "private_context_egress_denied", excluded_source_types=("memory", "knowledge"))


def partition_context(items, destination_class: DestinationClass, user_authorized_private_context: bool):
    """Return (transmissible, excluded_refs) for the provider payload."""
    transmissible = []
    excluded: list[str] = []
    for item in items:
        source_type = getattr(item, "source_type", "conversation")
        if destination_class is DestinationClass.CLOUD and source_type in {"memory", "knowledge"}:
            if not user_authorized_private_context:
                excluded.append(item.source_ref)
                continue
        transmissible.append(item)
    return transmissible, tuple(excluded)
