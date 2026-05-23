"""
Utility functions for AntiBlack system.
"""
import re
import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    short_uuid = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


def compute_text_hash(text: str) -> str:
    """Compute MD5 hash of text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def compute_simhash(text: str) -> int:
    """Compute SimHash for approximate deduplication."""
    # Simplified SimHash implementation
    # In production, use a proper SimHash library
    import struct
    hash_bytes = hashlib.md5(text.encode('utf-8')).digest()
    return struct.unpack('<Q', hash_bytes[:8])[0]


def hamming_distance(hash1: int, hash2: int) -> int:
    """Calculate Hamming distance between two hashes."""
    xor = hash1 ^ hash2
    return bin(xor).count('1')


def normalize_text(text: str) -> str:
    """Normalize text for processing."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Convert full-width to half-width
    text = str(text).translate(str.maketrans(
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    ))
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_entities_regex(text: str) -> List[Dict[str, Any]]:
    """Extract entities using regex patterns."""
    entities = []

    # WeChat
    wechat_pattern = r'[Vv微信]号?[:：]?\s*([a-zA-Z0-9_.-]{5,20})'
    for match in re.finditer(wechat_pattern, text):
        entities.append({
            "entity_type": "WECHAT",
            "entity_value": match.group(1),
            "source": "regex"
        })

    # Phone number (China mobile)
    phone_pattern = r'1[3-9]\d{9}'
    for match in re.finditer(phone_pattern, text):
        entities.append({
            "entity_type": "PHONE",
            "entity_value": match.group(0),
            "source": "regex"
        })

    # QQ number
    qq_pattern = r'[Qq号]+[:：]?\s*(\d{5,12})'
    for match in re.finditer(qq_pattern, text):
        entities.append({
            "entity_type": "QQ",
            "entity_value": match.group(1),
            "source": "regex"
        })

    # URL
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    for match in re.finditer(url_pattern, text):
        entities.append({
            "entity_type": "URL",
            "entity_value": match.group(0),
            "source": "regex"
        })

    # Email
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    for match in re.finditer(email_pattern, text):
        entities.append({
            "entity_type": "EMAIL",
            "entity_value": match.group(0),
            "source": "regex"
        })

    # Price
    price_pattern = r'(\d+(?:\.\d+)?)\s*(?:元|块|块大洋|rmb|RMB)?'
    for match in re.finditer(price_pattern, text):
        entities.append({
            "entity_type": "PRICE",
            "entity_value": match.group(0),
            "source": "regex"
        })

    return entities


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


def calculate_routing_score(
    risk_level: str,
    entity_count: int,
    slang_count: int,
    text_length: int,
    source_authority: str = "medium"
) -> float:
    """Calculate routing score for channel分流 decision."""
    # Base score from risk level
    risk_score = {
        'HIGH': 1.0,
        'MEDIUM': 0.5,
        'LOW': 0.2,
        'NORMAL': 0.0
    }.get(risk_level, 0.0)

    # Entity density (normalized to 0-0.3)
    entity_score = min(0.3, entity_count / 10)

    # Semantic complexity (based on slang density)
    if text_length > 0:
        slang_density = slang_count / (text_length / 100)
    else:
        slang_density = 0
    complexity_score = min(0.2, slang_density * 0.1)

    # Source authority
    authority_score = {
        'high': 0.15,
        'medium': 0.075,
        'low': 0.0
    }.get(source_authority, 0.075)

    return risk_score + entity_score + complexity_score + authority_score


def format_error_response(code: int, message: str, request_id: Optional[str] = None) -> Dict[str, Any]:
    """Format error response."""
    return {
        "code": code,
        "message": message,
        "request_id": request_id or generate_id("req"),
        "data": None
    }


def format_success_response(data: Any, request_id: Optional[str] = None, message: str = "ok") -> Dict[str, Any]:
    """Format success response."""
    return {
        "code": 0,
        "message": message,
        "request_id": request_id or generate_id("req"),
        "data": data
    }


from datetime import timedelta