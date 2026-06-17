"""
agent/tools/__init__.py

Tool registry entry point. Importing this package triggers registration
of all built-in tool modules (search_clues, kg_query, etc.) by way of
their @register_tool decorators at module-load time.

Usage in services/orchestrator.py::

    from agent.tools import invoke_tool, get_tools_by_names, list_all
    schemas = get_tools_by_names(["search_clues", "kg_query"])
    result = await invoke_tool("search_clues", self, query="诈骗")
"""
from agent.tools.registry import (
    register_tool,
    get_tools_by_names,
    invoke_tool,
    list_all,
    reset_for_tests,
    get_entry,
)

# Import each built-in tool module so its @register_tool runs.
# Order doesn't matter; what matters is that *some* module triggers
# registration. Add new tools by dropping a file in this directory.
from agent.tools import (  # noqa: F401
    search_clues,
    get_recent_clues,
    search_entities,
    search_slang,
    get_clue_detail,
    kg_query,
    aggregate_clue_stats,
    get_actor_footprint,
)


__all__ = [
    "register_tool",
    "get_tools_by_names",
    "invoke_tool",
    "list_all",
    "reset_for_tests",
]
