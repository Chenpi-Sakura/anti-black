"""
Unit tests for the agent/tools/ registry.

Verifies:
  - All 8 expected tools register on import
  - get_tools_by_names filters and preserves order
  - invoke_tool dispatches to the right handler with kwargs
  - Unknown tool names raise ValueError
  - Duplicate @register_tool raises at import time
"""
import asyncio
import pytest

import agent.tools  # triggers @register_tool decorators
from agent.tools import (
    register_tool,
    get_tools_by_names,
    invoke_tool,
    list_all,
    reset_for_tests,
    get_entry,
)


EXPECTED_TOOLS = {
    "search_clues",
    "get_recent_clues",
    "search_entities",
    "search_slang",
    "get_clue_detail",
    "kg_query",
    "aggregate_clue_stats",
    "get_actor_footprint",
}


def test_all_eight_tools_registered():
    """All 8 hardcoded tools from the original TOOLS list should auto-register."""
    assert set(list_all()) == EXPECTED_TOOLS, (
        f"Missing tools: {EXPECTED_TOOLS - set(list_all())}; "
        f"Extra tools: {set(list_all()) - EXPECTED_TOOLS}"
    )


def test_get_tools_by_names_filters():
    schemas = get_tools_by_names(["search_clues", "kg_query"])
    assert len(schemas) == 2
    assert {s["function"]["name"] for s in schemas} == {"search_clues", "kg_query"}


def test_get_tools_by_names_preserves_order():
    """Order matters — Skill bundles expect tools listed in invocation order."""
    schemas = get_tools_by_names(["kg_query", "search_clues"])
    assert [s["function"]["name"] for s in schemas] == ["kg_query", "search_clues"]


def test_get_tools_by_names_skips_unknown(caplog):
    """Unknown names are silently skipped, not raised — stale Skill configs
    shouldn't break the orchestrator."""
    schemas = get_tools_by_names(["search_clues", "nonexistent_tool_xyz"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "search_clues"


def test_invoke_tool_dispatches_with_kwargs():
    """invoke_tool should call the registered factory with the bound
    orchestrator, then forward **kwargs to the returned runner."""
    # Use a stub orchestrator with a known return value
    class StubOrch:
        def __init__(self):
            self.calls = []

        async def _search_clues(self, query, limit=50, **_):
            self.calls.append({"query": query, "limit": limit})
            return [{"clue_id": "stub_1", "raw_text": query}]

    orch = StubOrch()
    result = asyncio.run(invoke_tool("search_clues", orch, query="诈骗", limit=5))
    assert result == [{"clue_id": "stub_1", "raw_text": "诈骗"}]
    assert orch.calls == [{"query": "诈骗", "limit": 5}]


def test_invoke_tool_unknown_raises():
    """Unknown tool should raise ValueError so the orchestrator can return
    {"error": "Unknown tool: X"} to the LLM."""
    with pytest.raises(ValueError, match="Unknown tool"):
        asyncio.run(invoke_tool("does_not_exist", object()))


def test_duplicate_register_raises():
    """Two @register_tool(name="x", ...) decorators should fail loudly."""

    @register_tool(name="dup_tool_test", description="first", parameters={})
    def first(orch):
        async def run():
            return None
        return run

    with pytest.raises(ValueError, match="already registered"):
        @register_tool(name="dup_tool_test", description="second", parameters={})
        def second(orch):
            async def run():
                return None
            return run

    # Cleanup: the first registration persists in the live registry. Use
    # reset_for_tests to wipe so other tests aren't affected.
    reset_for_tests()
    # Re-import the real tools to restore the 8 entries.
    import importlib
    import agent.tools.search_clues
    import agent.tools.get_recent_clues
    import agent.tools.search_entities
    import agent.tools.search_slang
    import agent.tools.get_clue_detail
    import agent.tools.kg_query
    import agent.tools.aggregate_clue_stats
    import agent.tools.get_actor_footprint
    for m in [
        agent.tools.search_clues,
        agent.tools.get_recent_clues,
        agent.tools.search_entities,
        agent.tools.search_slang,
        agent.tools.get_clue_detail,
        agent.tools.kg_query,
        agent.tools.aggregate_clue_stats,
        agent.tools.get_actor_footprint,
    ]:
        importlib.reload(m)
    assert set(list_all()) == EXPECTED_TOOLS
