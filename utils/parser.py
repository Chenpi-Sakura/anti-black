import re
from datetime import datetime, timedelta
from typing import List, Tuple, Optional


def parse_time_range(query_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse time range from natural language query."""
    now = datetime.utcnow()
    start_time = None
    end_time = None

    # Match "近X天"
    days_match = re.search(r'近(\d+)天', query_text)
    if days_match:
        days = int(days_match.group(1))
        start_time = (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
        end_time = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')

    # Match "最近X天"
    recent_days_match = re.search(r'最近(\d+)天', query_text)
    if recent_days_match:
        days = int(recent_days_match.group(1))
        start_time = (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
        end_time = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')

    return start_time, end_time


def parse_platform(query_text: str) -> List[str]:
    """Parse platform mentions from query."""
    platforms = []
    query_lower = query_text.lower()

    platform_keywords = {
        '抖音': ['抖音', '抖号', 'douyin'],
        '快手': ['快手', 'ks'],
        '小红书': ['小红书', 'rednote', 'redbook'],
        '微信': ['微信', 'wechat'],
        'Telegram': ['telegram', 'tg', '飞机', '电报'],
        '贴吧': ['贴吧', 'tieba'],
        '闲鱼': ['闲鱼', 'xianyu'],
        '转转': ['转转', 'zhuanzhuan']
    }

    for platform, keywords in platform_keywords.items():
        if any(kw in query_lower for kw in keywords):
            platforms.append(platform)

    return platforms


def parse_risk_type(query_text: str) -> List[str]:
    """Parse risk type from query."""
    risk_types = []
    query_lower = query_text.lower()

    risk_keywords = {
        '账号交易': ['账号交易', '账号买卖', '出号', '换绑', '租号', '账号转让'],
        '流量作弊': ['刷粉', '刷赞', '刷量', '流量作弊', '涨粉'],
        '诈骗引流': ['诈骗', '引流', '刷单', '杀猪盘', '兼职诈骗'],
        '黑产工具': ['接码', '群控', '黑产工具', '脚本']
    }

    for risk_type, keywords in risk_keywords.items():
        if any(kw in query_lower for kw in keywords):
            risk_types.append(risk_type)

    return risk_types
