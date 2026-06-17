"""
agent/tools/get_clue_detail.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="get_clue_detail",
    description=(
        "Fetch a single clue's full content by clue_id. Returns raw_text, "
        "entity_list, slang_mappings, graph_relations. Call AFTER search_clues "
        "when a specific clue_id needs deeper inspection."
    ),
    parameters={
        "type": "object",
        "properties": {
            "clue_id": {
                "type": "string",
                "description": "The clue_id, e.g. 'clue_20260608_063205_d5d63ebb'. Required.",
            },
        },
        "required": ["clue_id"],
    },
)
def get_clue_detail(orch):
    async def run(clue_id=""):
        return await orch._get_clue_detail(clue_id=clue_id)

    return run
