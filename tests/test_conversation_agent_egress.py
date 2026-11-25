from types import SimpleNamespace

from core.conversation_agent.contracts import DestinationClass
from core.conversation_agent.egress import (
    authorize_transmission,
    classify_destination,
    partition_context,
)


def item(source_type, ref):
    return SimpleNamespace(source_type=source_type, source_ref=ref)


def test_destination_classification():
    assert classify_destination("ollama") is DestinationClass.LOCAL
    assert classify_destination("openrouter") is DestinationClass.CLOUD
    assert classify_destination(None) is DestinationClass.NONE


def test_conversation_only_cloud_content_is_allowed():
    decision = authorize_transmission("openrouter", includes_private_context=False, user_authorized_private_context=False)
    assert decision.allowed


def test_private_context_cloud_denied_without_authorization():
    decision = authorize_transmission("openrouter", includes_private_context=True, user_authorized_private_context=False)
    assert not decision.allowed
    assert "memory" in decision.excluded_source_types


def test_private_context_cloud_allowed_with_explicit_authorization():
    decision = authorize_transmission("openrouter", includes_private_context=True, user_authorized_private_context=True)
    assert decision.allowed


def test_local_destination_never_denied():
    decision = authorize_transmission("ollama", includes_private_context=True, user_authorized_private_context=False)
    assert decision.allowed


def test_partition_excludes_private_on_cloud():
    items = [item("conversation", "message:1"), item("memory", "memory:9"), item("knowledge", "knowledge:1:chunk:2")]
    transmissible, excluded = partition_context(items, DestinationClass.CLOUD, False)
    assert [i.source_ref for i in transmissible] == ["message:1"]
    assert set(excluded) == {"memory:9", "knowledge:1:chunk:2"}


def test_partition_keeps_private_on_local():
    items = [item("conversation", "message:1"), item("memory", "memory:9")]
    transmissible, excluded = partition_context(items, DestinationClass.LOCAL, False)
    assert len(transmissible) == 2 and excluded == ()
