"""
Extractor module for AntiBlack pipeline.
Handles entity extraction from messages.
"""
import logging
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """Extracted entity."""
    entity_id: str
    entity_type: str
    entity_value: str
    source: str  # regex/ocr/vlm/deep_channel
    context: str


@dataclass
class ExtractionResult:
    """Extraction result with entities and slang mappings."""
    message_id: str
    entities: List[ExtractedEntity]
    slang_mappings: List[Dict[str, str]]
    platform: Optional[str] = None


class Extractor:
    """Entity extractor using regex and dictionary matching."""

    # Entity patterns
    ENTITY_PATTERNS = {
        'WECHAT': [
            r'[Vv微信]号?[:：]?\s*([a-zA-Z0-9_.-]{5,20})',
            r'加微\s*[@:：]\s*([a-zA-Z0-9_.-]{5,20})',
            r'微信号\s*[@:：]?\s*([a-zA-Z0-9_.-]{5,20})',
        ],
        'PHONE': [
            r'1[3-9]\d{9}',  # China mobile
            r'\+86\s*1[3-9]\d{9}',
        ],
        'QQ': [
            r'[Qq号]+[:：]?\s*(\d{5,12})',
            r'QQ\s*[@:：]?\s*(\d{5,12})',
        ],
        'URL': [
            r'https?://[^\s<>"{}|\\^`\[\]]+',
            r'www\.[^\s<>"{}|\\^`\[\]]+',
        ],
        'EMAIL': [
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        ],
    }

    # Price patterns
    PRICE_PATTERNS = [
        r'(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)',
        r'价格\s*[@:：]?\s*(\d+(?:\.\d+)?)',
    ]

    # Platform keywords
    PLATFORM_KEYWORDS = {
        '抖音': ['抖音', '抖号', 'douyin'],
        '快手': ['快手', 'ks'],
        '小红书': ['小红书', 'rednote'],
        '微信': ['微信', 'wechat'],
        '闲鱼': ['闲鱼', 'xianyu'],
    }

    def __init__(self, slang_mappings: Dict[str, str] = None):
        self.slang_mappings = slang_mappings or {}

    def extract(self, message_id: str, text: str, cleaned_text: str = None) -> ExtractionResult:
        """Extract entities from message text."""
        cleaned_text = cleaned_text or text
        entities = []
        slang_mappings = []

        # Extract entities using regex
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    entity_value = match.group(1) if match.lastindex else match.group(0)
                    entities.append(ExtractedEntity(
                        entity_id=self._generate_entity_id(entity_type, entity_value),
                        entity_type=entity_type,
                        entity_value=entity_value,
                        source='regex',
                        context=self._get_context(text, match.start(), match.end())
                    ))

        # Extract prices
        for pattern in self.PRICE_PATTERNS:
            for match in re.finditer(pattern, text):
                price_value = match.group(0)
                entities.append(ExtractedEntity(
                    entity_id=self._generate_entity_id('PRICE', price_value),
                    entity_type='PRICE',
                    entity_value=price_value,
                    source='regex',
                    context=self._get_context(text, match.start(), match.end())
                ))

        # Extract slang mappings
        for slang_raw, meaning in self.slang_mappings.items():
            if slang_raw.lower() in text.lower():
                slang_mappings.append({
                    'slang_raw': slang_raw,
                    'meaning': meaning
                })

        # Detect platform
        platform = self._detect_platform(text)

        return ExtractionResult(
            message_id=message_id,
            entities=entities,
            slang_mappings=slang_mappings,
            platform=platform
        )

    def _detect_platform(self, text: str) -> Optional[str]:
        """Detect platform from text."""
        text_lower = text.lower()
        for platform, keywords in self.PLATFORM_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return platform
        return None

    def _generate_entity_id(self, entity_type: str, value: str) -> str:
        """Generate entity ID."""
        import hashlib
        value_hash = hashlib.md5(f"{entity_type}:{value}".encode()).hexdigest()[:12]
        return f"ent_{entity_type.lower()}_{value_hash}"

    def _get_context(self, text: str, start: int, end: int, context_size: int = 20) -> str:
        """Get surrounding context for entity."""
        ctx_start = max(0, start - context_size)
        ctx_end = min(len(text), end + context_size)
        return text[ctx_start:ctx_end]

    def extract_batch(self, messages: List[Dict[str, str]]) -> List[ExtractionResult]:
        """Extract entities from a batch of messages."""
        results = []
        for msg in messages:
            result = self.extract(
                message_id=msg.get('message_id', ''),
                text=msg.get('raw_text', ''),
                cleaned_text=msg.get('cleaned_text')
            )
            results.append(result)
        return results