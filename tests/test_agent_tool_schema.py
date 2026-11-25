"""Regression coverage for the bounded knowledge_search output schema (WP-6.7)."""
from __future__ import annotations

import pytest

from core.agents.bootstrap import _knowledge_search_definition
from core.tools.registry import ToolInputValidationError, ToolRegistry


def _valid_output():
    return {
        "count": 1,
        "truncated": False,
        "results": [
            {
                "source_id": "0123456789abcdef0123456789abcdef",
                "chunk_id": 7,
                "title": "Seeded source",
                "source_type": "text",
                "uri": "",
                "rank": 0.75,
                "content": "durable storage facts",
            }
        ],
    }


def _registry_with_builtin():
    async def handler(input_data):
        return _valid_output()

    registry = ToolRegistry()
    definition = _knowledge_search_definition()
    # Registration itself proves the declared schema satisfies the restricted
    # bounded-schema rules (unsupported keywords or unbounded depth would fail).
    registry.register(definition, handler)
    return registry, definition


def test_valid_knowledge_search_results_pass_the_registered_schema():
    registry, definition = _registry_with_builtin()
    validated = registry.validate_output(definition, _valid_output())
    assert validated["count"] == 1
    assert validated["truncated"] is False
    assert validated["results"][0]["chunk_id"] == 7
    assert validated["results"][0]["source_id"] == "0123456789abcdef0123456789abcdef"


def test_malformed_knowledge_search_outputs_are_rejected():
    registry, definition = _registry_with_builtin()
    valid = _valid_output()

    missing_count = {key: value for key, value in valid.items() if key != "count"}
    with pytest.raises(ToolInputValidationError, match="missing required fields"):
        registry.validate_output(definition, missing_count)

    extra_field = dict(valid)
    extra_field["unexpected"] = True
    with pytest.raises(ToolInputValidationError, match="unsupported fields"):
        registry.validate_output(definition, extra_field)

    malformed_result = dict(valid)
    malformed_result["results"] = [dict(valid["results"][0], chunk_id="seven")]
    with pytest.raises(ToolInputValidationError, match="chunk_id"):
        registry.validate_output(definition, malformed_result)

    oversized_count = dict(valid, count=11)
    with pytest.raises(ToolInputValidationError, match="count"):
        registry.validate_output(definition, oversized_count)

    oversized_content = dict(valid)
    oversized_content["results"] = [dict(valid["results"][0], content="x" * 401)]
    with pytest.raises(ToolInputValidationError, match="content"):
        registry.validate_output(definition, oversized_content)


def test_the_builtin_definition_matches_its_registered_identity():
    registry, definition = _registry_with_builtin()
    stored = registry.get_definition("knowledge_search", "1.0.0")
    assert stored.tool_id == definition.tool_id
    assert stored.output_schema == definition.output_schema
    assert stored.resource_type is definition.resource_type
    assert stored.operation is definition.operation
