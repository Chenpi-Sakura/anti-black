import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


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
