"""
agent/tools/registry.py

MCP-style tool registry. Each tool module under agent/tools/ decorates its
handler with @register_tool() at import time. The Orchestrator binds a
live instance to invoke_tool() once process_query starts.

Design:
  - @register_tool(name, description, parameters) — schema is the OpenAI
    function-calling format (same shape as the original TOOLS list in
    services/orchestrator.py:68-298).
  - get_tools_by_names(names) — returns schemas filtered to the names
    requested (e.g. by a Skill bundle). Used to send only the relevant
    tools to the LLM in tool_choice=auto mode.
  - invoke_tool(name, orchestrator_instance, **kwargs) — dispatch entry
    point. Handler signature is (orchestrator, **kwargs) -> dict.
  - list_all() — list every registered tool name (for admin / debug).

Why bind orchestrator at call time (not at @register_tool):
  Tools call self.db / self.llm / self._kg_query on the Orchestrator
  instance. Importing Orchestrator at module load time would force a
  circular import (agent/tools/<x> -> services.orchestrator -> imports
  -> back to agent/). Late binding via a closure passed to invoke_tool
  breaks the cycle. See agent/tools/search_clues.py for the pattern.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional


# name -> {schema, handler}
# handler: Callable[[Orchestrator], Awaitable[Any]] -- a *factory* that
# takes a bound orchestrator and returns an awaitable that calls the
# matching private method on that instance. We don't pass args here
# because the factory is built once at import time per tool; invoke_tool
# forwards **kwargs to the returned awaitable.
ToolHandler = Callable[[Any], Awaitable[Any]]
ToolFactory = Callable[[Any], Callable[..., Awaitable[Any]]]

_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_tool(
    name: str,
    description: str,
    parameters: dict,
) -> Callable[[ToolFactory], ToolFactory]:
    """Decorator. Wraps a tool factory with its OpenAI schema.

    Usage in agent/tools/search_clues.py::

        @register_tool(
            name="search_clues",
            description="Search clues by keyword ...",
            parameters={...},
        )
        def search_clues(orch):
            async def run(query, time_range=None, ...):
                return await orch._search_clues(query, ...)
            return run
    """
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }

    def deco(factory: ToolFactory) -> ToolFactory:
        if name in _REGISTRY:
            raise ValueError(f"Tool '{name}' already registered (duplicate @register_tool)")
        _REGISTRY[name] = {
            "schema": schema,
            "factory": factory,
            "name": name,
            "description": description,
        }
        return factory

    return deco


def get_tools_by_names(names: List[str]) -> List[dict]:
    """Return schemas for the named tools, preserving input order.

    Unknown names are silently skipped (with a debug log); a Skill that
    references a stale tool name will simply get a shorter tool list
    rather than crashing. Callers can check list_all() to verify.
    """
    import logging
    log = logging.getLogger(__name__)
    out: List[dict] = []
    for n in names:
        entry = _REGISTRY.get(n)
        if entry is None:
            log.warning(f"get_tools_by_names: unknown tool '{n}', skipping")
            continue
        out.append(entry["schema"])
    return out


async def invoke_tool(name: str, orchestrator: Any, **kwargs) -> Any:
    """Dispatch a tool call to its handler bound to the given orchestrator.

    Raises ValueError on unknown tool name (caller should send SSE error
    back to the LLM as {"error": "Unknown tool: X"}).
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"Unknown tool: {name}")
    # Build the bound runner once per call (cheap: just a closure over orch).
    runner = entry["factory"](orchestrator)
    return await runner(**kwargs)


def list_all() -> List[str]:
    """Return all registered tool names (sorted)."""
    return sorted(_REGISTRY.keys())


def get_entry(name: str) -> Optional[Dict[str, Any]]:
    """Return the full registry entry (for tests / debug)."""
    return _REGISTRY.get(name)


def reset_for_tests() -> None:
    """Clear the registry. Test-only — never call from production code."""
    _REGISTRY.clear()
