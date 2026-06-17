"""
agent/tools/get_actor_footprint.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="get_actor_footprint",
    description=(
        "Entity activity timeline across platforms. Input a WeChat ID / phone "
        "/ QQ, returns: timeline by date+channel, risk label history, recent "
        "clues, entity metadata. Use for 'what else did this account do', "
        "'actor profile/portrait', 'track record across channels'. entity_type "
        "is optional but helps precision when known."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_value": {
                "type": "string",
                "description": "Entity identifier: WeChat ID, phone number, QQ number, or any source_author_id. Required.",
            },
            "entity_type": {
                "type": "string",
                "description": "Entity type hint (optional, narrows entity-table search): 'WeChat', 'phone', 'QQ', 'account'.",
            },
            "limit": {
                "type": "integer",
                "description": "Max recent clues to return. Default 50.",
                "default": 50,
            },
        },
        "required": ["entity_value"],
    },
)
def get_actor_footprint(orch):
    async def run(entity_value="", entity_type=None, limit=50):
        return await orch._get_actor_footprint(
            entity_value=entity_value,
            entity_type=entity_type,
            limit=limit,
        )

    return run
