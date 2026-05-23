"""
Classification module for AntiBlack pipeline.
Handles intent classification with rule/model/LLM三层分类.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Classification result."""
    level1_label: str
    level2_label: str
    confidence: float
    source: str  # rule/model/llm
    reason: str


class ClassificationRule:
    """Single classification rule."""

    def __init__(self, patterns: List[str], level1: str, level2: str, confidence: float = 0.9):
        self.patterns = patterns
        self.level1 = level1
        self.level2 = level2
        self.confidence = confidence

    def match(self, text: str) -> bool:
        """Check if text matches this rule."""
        for pattern in self.patterns:
            if pattern in text.lower():
                return True
        return False


class Classifier:
    """Multi-stage classifier with rule/model/LLM fallback."""

    # Predefined rules from taxonomy
    DEFAULT_RULES = [
        # Account trading rules
        ClassificationRule(
            patterns=['出号', '换绑', '租号', '抖号', '快手号', '微信号'],
            level1='账号交易',
            level2='账号买卖',
            confidence=0.95
        ),
        ClassificationRule(
            patterns=['抖音号买卖', '快手号出租', '账号转让'],
            level1='账号交易',
            level2='账号买卖',
            confidence=0.95
        ),
        # Traffic cheating rules
        ClassificationRule(
            patterns=['刷粉', '涨粉', '千粉', '万粉', '粉丝'],
            level1='流量作弊',
            level2='刷粉',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['刷赞', '点赞', '刷量'],
            level1='流量作弊',
            level2='刷赞',
            confidence=0.9
        ),
        # Fraud rules
        ClassificationRule(
            patterns=['刷单', '兼职', '佣金'],
            level1='诈骗引流',
            level2='刷单引流',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['杀猪盘', '投资', '导师'],
            level1='诈骗引流',
            level2='杀猪盘',
            confidence=0.85
        ),
        # Black tools rules
        ClassificationRule(
            patterns=['接码', '验证码', '手机号'],
            level1='黑产工具',
            level2='接码平台',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['群控', '脚本', '自动化'],
            level1='黑产工具',
            level2='群控工具',
            confidence=0.9
        ),
    ]

    def __init__(self, config: Dict[str, Any] = None, rules: List[ClassificationRule] = None):
        self.config = config or {}
        self.rules = rules or self.DEFAULT_RULES
        self.rule_threshold = self.config.get('classification', {}).get('rule_confidence_threshold', 0.9)
        self.embedding_threshold = self.config.get('classification', {}).get('embedding_confidence_threshold', 0.6)
        self.llm_threshold = self.config.get('classification', {}).get('llm_fallback_confidence', 0.6)

    def classify(self, text: str, context: Dict[str, Any] = None) -> ClassificationResult:
        """
        Classify text using three-stage classification.

        1. Rule-based (fast, high confidence for clear patterns)
        2. Embedding model (medium confidence)
        3. LLM fallback (low confidence or ambiguous cases)
        """
        context = context or {}

        # Stage 1: Rule classification
        result = self._classify_by_rules(text)
        if result and result.confidence >= self.rule_threshold:
            logger.debug(f"Rule classification: {result.level1_label}/{result.level2_label}")
            return result

        # Stage 2: Embedding model (simplified for demo)
        result = self._classify_by_embedding(text, context)
        if result and result.confidence >= self.embedding_threshold:
            logger.debug(f"Embedding classification: {result.level1_label}/{result.level2_label}")
            return result

        # Stage 3: LLM fallback (return unknown if LLM not available)
        result = self._classify_by_llm(text, context)
        if result:
            logger.debug(f"LLM classification: {result.level1_label}/{result.level2_label}")
            return result

        # Default to unknown
        return ClassificationResult(
            level1_label='未知/其他',
            level2_label='未分类',
            confidence=0.5,
            source='rule',
            reason='未匹配到明确风险类型'
        )

    def _classify_by_rules(self, text: str) -> Optional[ClassificationResult]:
        """Classify using predefined rules."""
        text_lower = text.lower()

        for rule in self.rules:
            if rule.match(text_lower):
                return ClassificationResult(
                    level1_label=rule.level1,
                    level2_label=rule.level2,
                    confidence=rule.confidence,
                    source='rule',
                    reason=f'命中规则: {rule.patterns}'
                )

        return None

    def _classify_by_embedding(self, text: str, context: Dict[str, Any]) -> Optional[ClassificationResult]:
        """
        Classify using embedding model.
        In production, this would use a trained classifier on embeddings.
        For demo, we simulate with lower confidence.
        """
        # In production: use sentence-transformers + trained classifier
        # For demo: return None to fall back to LLM
        return None

    def _classify_by_llm(self, text: str, context: Dict[str, Any]) -> Optional[ClassificationResult]:
        """
        Classify using LLM.
        In production, this would call the LLM API.
        For demo, we return a mock result.
        """
        # In production: call LLM API
        # For demo: return None to use default
        return None

    def classify_batch(self, texts: List[str], context: Dict[str, Any] = None) -> List[ClassificationResult]:
        """Classify a batch of texts."""
        return [self.classify(text, context) for text in texts]


def build_taxonomy_mapping(taxonomy_config: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Build taxonomy lookup from config."""
    mapping = {}

    for category in taxonomy_config.get('categories', []):
        level1_code = category.get('level1_code', '')
        level1_name = category.get('level1_name', '')

        for item in category.get('level2_items', []):
            level2_code = item.get('level2_code', '')
            level2_name = item.get('level2_name', '')

            mapping[level1_code] = {
                'name': level1_name,
                'level2': {
                    level2_code: level2_name
                }
            }

    return mapping