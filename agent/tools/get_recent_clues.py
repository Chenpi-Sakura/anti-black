"""
agent/tools/get_recent_clues.py — see search_clues.py for design pattern.
"""
from agent.tools.registry import register_tool


@register_tool(
    name="get_recent_clues",
    description=(
        "Simpler time-window alternative to search_clues. Parameters: hours "
        "(int, default 24), risk_label_level1, platform. Use when user asks "
        "'last N hours' without needing keyword/or-platform-list filters."
    ),
    parameters={
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": "Look-back window in hours. Default 24 (last 24h).",
                "default": 24,
            },
            "risk_label_level1": {
                "type": "string",
                "description": (
                    "Single risk type filter (optional): account_trading, fraud_leads, "
                    "traffic_cheating, black_tools, money_laundering, unknown, irrelevant. "
                    "Only one allowed."
                ),
            },
            "platform": {
                "type": "string",
                "description": "Single platform filter (optional): douyin, baidu_tieba, weibo, xiaohongshu, kuaishou.",
            },
            "limit": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        },
    },
)
def get_recent_clues(orch):
    async def run(hours=24, risk_label_level1=None, platform=None, limit=20):
        return await orch._get_recent_clues(
            hours=hours,
            risk_label_level1=risk_label_level1,
            platform=platform,
            limit=limit,
        )

    return run
