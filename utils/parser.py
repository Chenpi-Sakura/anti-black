import re
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

# Beijing timezone (UTC+8)
_BJT = timezone(timedelta(hours=8))


def parse_time_range(query_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse time range from natural language query.

    Supported inputs (case-insensitive):
      - 今天 / 今日             → 当天 00:00 → now
      - 昨天 / 昨日             → 昨天 00:00 → 今天 00:00
      - 本周                   → 本周一 00:00 → now
      - 本月                   → 本月1号 00:00 → now
      - 近N天 / 最近N天          → N 天前 → now
      - 近一周                  → 7 天前 → now
      - 近一个月 / 近一月         → 30 天前 → now
      - 近三个月 / 近三月         → 90 天前 → now

    Returns (start_iso, end_iso) both in Asia/Shanghai (UTC+8).
    If the input can't be parsed, returns (None, None).
    """
    now = datetime.now(_BJT)
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    def _fmt(dt: datetime) -> str:
        return dt.isoformat()

    text = query_text.strip().lower()

    # -- absolute keywords (bilingual) -----------------------------------
    if text in ("今天", "今日", "today"):
        start_time = _fmt(now.replace(hour=0, minute=0, second=0, microsecond=0))
        end_time = _fmt(now)
        return start_time, end_time

    if text in ("昨天", "昨日", "yesterday"):
        yesterday = now - timedelta(days=1)
        start_time = _fmt(yesterday.replace(hour=0, minute=0, second=0, microsecond=0))
        end_time = _fmt(now.replace(hour=0, minute=0, second=0, microsecond=0))
        return start_time, end_time

    if text in ("本周", "this week"):
        monday = now - timedelta(days=now.weekday())
        start_time = _fmt(monday.replace(hour=0, minute=0, second=0, microsecond=0))
        end_time = _fmt(now)
        return start_time, end_time

    if text in ("本月", "this month"):
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_time = _fmt(first)
        end_time = _fmt(now)
        return start_time, end_time

    # -- relative keywords (bilingual) -----------------------------------
    # 近一周 / 近一个月 / 近三月 / 近三个月 / last N days / past N days
    unit_map = {"一周": 7, "一个月": 30, "一月": 30, "三月": 90, "三个月": 90,
                "week": 7, "month": 30, "quarter": 90}
    for unit, days in unit_map.items():
        if unit in text and ("近" in text or "last" in text or "past" in text):
            start_time = _fmt(now - timedelta(days=days))
            end_time = _fmt(now)
            return start_time, end_time

    # 近X天 / 最近X天 / last N days / past N days
    # Arabic digits: 近7天 or last 7 days
    # Chinese digits: 近三天
    _CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0}
    days_match = re.search(r'(?:(?:近|最近)(\d+)天|(?:last|past)\s+(\d+)\s+days?)', text)
    if not days_match:
        days_match = re.search(r'(?:近|最近)([一两三四五六七八九十半])(?:天)?', text)
    if days_match:
        dg = days_match.group(1)
        days = int(dg) if dg.isdigit() else _CN_DIGITS.get(dg, 7)
        start_time = _fmt(now - timedelta(days=days))
        end_time = _fmt(now)
        return start_time, end_time

    # fallback: no pattern matched
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
