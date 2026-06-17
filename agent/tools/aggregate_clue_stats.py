"""
agent/tools/aggregate_clue_stats.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="aggregate_clue_stats",
    description=(
        "AGGREGATE (not search). SQL GROUP BY on 110K+ clues — count "
        "distribution by risk_type, platform, or cross-dimension. Use for "
        "'trend', 'today breakdown', 'top 3', 'growth rate', 'change over "
        "time' queries. NOT a search tool — does NOT return individual clue "
        "text. When user asks about trends/ranking/distribution, ALWAYS call "
        "this first instead of guessing from search_clues samples."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time_range": {
                "type": "object",
                "description": (
                    "Time window as {amount, unit}. E.g. {amount:1, unit:'day'} "
                    "= today, {amount:30, unit:'day'} = this month. Omit or set "
                    "amount=0 for all-time."
                ),
                "properties": {
                    "amount": {"type": "integer", "description": "How many units back, e.g. 1, 7, 30"},
                    "unit": {"type": "string", "description": "Time unit: 'day', 'hour', 'week', 'month'"},
                },
            },
            "group_by": {
                "type": "string",
                "description": (
                    "Aggregation dimension: 'risk_type' (by risk only), 'platform' "
                    "(by channel only, same as 'channel'), 'risk_platform' (cross "
                    "by risk+platform). Default: risk_platform."
                ),
                "default": "risk_platform",
            },
            "risk_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional risk type filter for the aggregation scope: "
                    "account_trading, fraud_leads, traffic_cheating, black_tools, "
                    "money_laundering, unknown, irrelevant."
                ),
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional platform filter: douyin, baidu_tieba, weibo, xiaohongshu, kuaishou.",
            },
        },
    },
)
def aggregate_clue_stats(orch):
    async def run(time_range="today", group_by="risk_platform", risk_types=None, platforms=None):
        return await orch._aggregate_clue_stats(
            time_range=time_range,
            group_by=group_by,
            risk_types=risk_types,
            platforms=platforms,
        )

    return run
