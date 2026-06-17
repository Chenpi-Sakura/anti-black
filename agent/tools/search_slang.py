"""
agent/tools/search_slang.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="search_slang",
    description=(
        "Look up slang terms in the slang dictionary (slang_mappings table). "
        "Matches against slang_raw or meaning column. Call when user asks "
        "'what does XX mean' or wants to see recent slang. For comprehensive "
        "slang coverage use this tool — search_clues only has sampled "
        "slang_mappings on its results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "slang_term": {
                "type": "string",
                "description": (
                    "Slang keyword or description, e.g. 'chuhao' (account selling), "
                    "'shuafen' (fake followers). Long sentences are auto-split into "
                    "2-gram keywords."
                ),
            },
            "limit": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        },
    },
)
def search_slang(orch):
    async def run(slang_term="", limit=20):
        return await orch._search_slang(slang_term=slang_term, limit=limit)

    return run
