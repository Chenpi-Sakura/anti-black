"""
agent/tools/kg_query.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="kg_query",
    description=(
        "Knowledge-graph structured retrieval (entities ↔ relationships ↔ "
        "chunks). Returns raw structured data — NO LLM summarization. Use for "
        "'who is connected to whom', 'entity relationship network', or 'find "
        "related entities around X'. Returns a dict with "
        "entities/relationships/chunks/references."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query text, e.g. 'Douyin account trading relationships', 'WeChat fraud connections'",
            },
            "mode": {
                "type": "string",
                "description": (
                    "Search mode: local (entity-first), global (relationship-first), "
                    "hybrid (balanced), mix (entity + relation + vector chunks, best "
                    "for comprehensive retrieval), naive (pure vector)"
                ),
                "default": "hybrid",
            },
            "limit": {
                "type": "integer",
                "description": "Max entities/relationships/chunks to return per category. 10 by default.",
                "default": 10,
            },
        },
    },
)
def kg_query(orch):
    async def run(query="", mode="hybrid", limit=10):
        return await orch._kg_query(query=query, mode=mode, limit=limit)

    return run
