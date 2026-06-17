"""
agent/tools/search_entities.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="search_entities",
    description=(
        "Search entity DB (WeChat IDs, phone numbers, QQ, accounts) by name or "
        "type. Returns matching entity nodes with metadata. Use when user "
        "mentions a specific identifier or wants to find known entities."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_name": {
                "type": "string",
                "description": "Entity name keyword, e.g. 'WeChat', 'account', or a specific ID",
            },
            "entity_type": {
                "type": "string",
                "description": "Entity type filter: WeChat, phone, QQ, account. Optional.",
            },
            "limit": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        },
    },
)
def search_entities(orch):
    async def run(entity_name="", entity_type=None, limit=20):
        return await orch._search_entities(
            entity_name=entity_name,
            entity_type=entity_type,
            limit=limit,
        )

    return run
