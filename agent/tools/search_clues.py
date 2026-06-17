"""
agent/tools/search_clues.py

MCP-style tool registration for the search_clues tool.
Schema is the same OpenAI function-calling format as the original
TOOLS list entry in services/orchestrator.py:73-115. The handler
is a thin wrapper that forwards to Orchestrator._search_clues so
the implementation stays single-sourced.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="search_clues",
    description=(
        "Search clues by keyword / risk_type / time / platform. Returns a LIST of "
        "clue summaries (no full text). Use for broad queries like 'find recent "
        "clue text about X'. For single-clue detail use get_clue_detail. Supports "
        "multi-value filters via array params."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "**MUST be Chinese keyword(s)** to match against clue text, e.g. "
                    "'微信号', '诈骗', '刷粉', '账号交易'. raw_text / cleaned_text are "
                    "stored in Chinese only — English keywords like 'WeChat' / 'fraud' "
                    "will return 0 results. If user mentions an English term, translate "
                    "to the Chinese equivalent (WeChat→微信号/卫星, fraud→诈骗/杀猪盘, "
                    "account trading→账号交易)."
                ),
            },
            "entity_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["WECHAT", "PHONE", "QQ", "ACCOUNT"],
                },
                "description": (
                    "Optional strong-signal filter on extracted entities. Filters by "
                    "entity_list JSONB column using GIN-indexed @> containment. Use "
                    "when the user query explicitly references a contact channel "
                    "(微信号/手机号/QQ) — combine with a Chinese query for the strongest "
                    "lock (e.g. user='涉及微信号的诈骗' → query='诈骗', "
                    "entity_types=['WECHAT'])."
                ),
            },
            "time_range": {
                "type": "object",
                "description": (
                    "Time window as {amount, unit}. E.g. {amount:1, unit:'day'} = last "
                    "1 day, {amount:7, unit:'day'} = last 7 days, omit = search all-time "
                    "(no time filter)."
                ),
                "properties": {
                    "amount": {"type": "integer", "description": "How many units back, e.g. 1, 7, 30"},
                    "unit": {"type": "string", "description": "Time unit: 'day', 'hour', 'week', 'month'"},
                },
            },
            "risk_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Risk level1 filter: account_trading, fraud_leads, traffic_cheating, "
                    "black_tools, money_laundering, unknown, irrelevant. Supply as array "
                    "— multi-value supported."
                ),
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Platform filter: douyin, baidu_tieba, weibo, xiaohongshu, kuaishou, "
                    "telegram. Multi-value supported."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return. 50 by default.",
                "default": 50,
            },
        },
    },
)
def search_clues(orch):
    """Factory: returns a runner that calls orch._search_clues with unpacked args."""

    async def run(query="", time_range=None, risk_types=None, platforms=None,
                  entity_types=None, limit=50):
        return await orch._search_clues(
            query=query,
            time_range=time_range,
            risk_types=risk_types,
            platforms=platforms,
            entity_types=entity_types,
            limit=limit,
        )

    return run
