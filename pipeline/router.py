"""
Router module for AntiBlack pipeline.
Handles routing decisions between light and deep channels.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


RISK_LABEL_TO_SCORE = {
    '账号交易': 'HIGH',
    '诈骗引流': 'HIGH',
    '黑产工具': 'HIGH',
    '流量作弊': 'MEDIUM',
    '未知/其他': 'LOW',
}


class Router:
    """
    Router for deciding message processing channel.
    Routes high-value messages to deep channel (LightRAG),
    low-value messages to light channel (rule-based extraction).
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        routing_config = self.config.get('pipeline', {}).get('routing', {})
        self.default_threshold = routing_config.get('default_threshold', 0.5)
        self.token_adjusted_threshold = routing_config.get('token_adjusted_threshold', 0.6)

        # Weights for scoring
        self.weights = {
            'risk_level': 0.5,  # Increased from 0.3
            'entity_density': 0.15,
            'semantic_complexity': 0.15,
            'novelty': 0.1,
            'source_authority': 0.1
        }

    def route(self, message: Dict[str, Any], token_budget_percent: float = 1.0) -> str:
        """
        Decide which channel to process the message.

        Args:
            message: Message data with classification and entity info
            token_budget_percent: Current token budget as percentage (0.0-1.0)

        Returns:
            'deep' for LightRAG processing
            'light' for rule-based extraction
        """
        score = self._calculate_score(message)

        # Adjust threshold based on token budget
        threshold = self.default_threshold
        if token_budget_percent < 0.3:
            threshold = self.token_adjusted_threshold

        if score >= threshold:
            logger.debug(f"Message {message.get('message_id')} routed to DEEP (score={score})")
            return 'deep'
        else:
            logger.debug(f"Message {message.get('message_id')} routed to LIGHT (score={score})")
            return 'light'

    def _calculate_score(self, message: Dict[str, Any]) -> float:
        """Calculate routing score for message."""
        score = 0.0

        # Risk level score - convert Chinese label to score key
        risk_label = message.get('risk_level', '未知/其他')
        risk_level = RISK_LABEL_TO_SCORE.get(risk_label, 'LOW')
        risk_scores = {'HIGH': 1.0, 'MEDIUM': 0.5, 'LOW': 0.2, 'NORMAL': 0.0}
        score += self.weights['risk_level'] * risk_scores.get(risk_level, 0.0)

        # Entity density score (0-0.3)
        entity_count = len(message.get('entities', []))
        entity_score = min(0.3, entity_count / 10)
        score += self.weights['entity_density'] * entity_score * 3  # Scale to 0-0.3

        # Semantic complexity (based on slang count)
        slang_count = len(message.get('slang_mappings', []))
        text_length = len(message.get('raw_text', ''))
        if text_length > 0:
            slang_density = slang_count / (text_length / 100)
        else:
            slang_density = 0
        complexity_score = min(0.2, slang_density * 0.1)
        score += self.weights['semantic_complexity'] * complexity_score * 5  # Scale to 0-0.2

        # Novelty (simplified - random加分 for demo)
        is_novel = message.get('is_novel', True)
        novelty_score = 0.15 if is_novel else 0.0
        score += self.weights['novelty'] * novelty_score

        # Source authority
        source = message.get('source_channel', 'telegram')
        authority_scores = {
            'telegram': 0.15,
            'forum': 0.10,
            'social': 0.05
        }
        authority_score = authority_scores.get(source, 0.05)
        score += self.weights['source_authority'] * authority_score * 3  # Scale to 0-0.15

        return min(1.0, score)  # Cap at 1.0

    def route_batch(self, messages: list, token_budget_percent: float = 1.0) -> Dict[str, list]:
        """Route a batch of messages, returning separate lists for each channel."""
        light_messages = []
        deep_messages = []

        for message in messages:
            channel = self.route(message, token_budget_percent)
            if channel == 'deep':
                deep_messages.append(message)
            else:
                light_messages.append(message)

        return {
            'light': light_messages,
            'deep': deep_messages
        }