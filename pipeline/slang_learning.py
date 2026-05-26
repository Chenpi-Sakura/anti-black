"""
Slang Learning module for AntiBlack pipeline.
Handles automatic discovery and learning of new slang terms.
"""
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class SlangCandidate:
    """A candidate slang term for learning."""
    word: str
    # contexts: List of (message_id, full_text) tuples for independent sample tracking
    contexts: List[tuple] = field(default_factory=list)
    occurrence_count: int = 0
    status: str = "NEW"  # NEW/OBSERVED/LIKELY/CONFIRMED/REJECTED/STABLE
    inference_count: int = 0
    regex_pattern: Optional[str] = None
    meaning: Optional[str] = None
    source_channel: Optional[str] = None
    reject_until: Optional[datetime] = None
    # FR-SLANG-03: 记录触发验证的消息ID，验证时排除该消息（独立样本原则）
    validation_trigger_msg_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class SlangLearner:
    """
    Slang learning module with progressive state machine.

    State transitions:
    NEW (1-5) -> OBSERVED (10, trigger inference) -> LIKELY (20, second inference)
      -> CONFIRMED (passes regex validation) -> STABLE (500 occurrences)
      OR REJECTED (failed validation after 3 retries, 30-day silence)
    """

    def __init__(self, config: Dict[str, Any], slang_mappings: Dict[str, str] = None):
        self.config = config
        self.slang_mappings = slang_mappings or {}

        # Get thresholds from config
        slang_config = config.get('slang_learning', {})
        thresholds = slang_config.get('thresholds', {})
        self.thresholds = {
            'new_to_observed': thresholds.get('new_to_observed', 10),
            'observed_to_likely': thresholds.get('observed_to_likely', 20),
            'likely_to_confirmed': thresholds.get('likely_to_confirmed', 50),
            'stable_count': thresholds.get('stable_count', 500)
        }

        reject_config = slang_config.get('reject', {})
        self.reject_config = {
            'silence_days': reject_config.get('silence_days', 30),
            'max_retries': reject_config.get('max_retries', 3)
        }

        # Token control
        token_control = slang_config.get('token_control', {})
        self.token_control = {
            'batch_size': token_control.get('batch_size', 20),
            'dynamic_threshold_factor': token_control.get('dynamic_threshold_factor', 1.5)
        }

        # In-memory candidate storage (in production, persist to DB)
        self._candidates: Dict[str, SlangCandidate] = {}

        # Known words to skip
        self._known_words: Set[str] = set(slang_mappings.keys()) if slang_mappings else set()

        # Regex patterns for validation
        self._validation_patterns = [
            r'^[一-鿿]+$',  # Chinese characters only
            r'^[\w]+$',  # Alphanumeric only
        ]

    def process_text(self, text: str, source_channel: str = None, message_id: str = None) -> List[SlangCandidate]:
        """
        Process text to find new slang candidates.

        Args:
            text: Full original text of the message
            source_channel: Source channel (e.g., 'douyin', 'tieba')
            message_id: Unique message identifier for independent sample tracking (FR-SLANG-03)

        Returns list of newly discovered candidates.
        """
        discovered = []
        words = self._extract_words(text)

        # Generate message_id if not provided
        if message_id is None:
            message_id = f"{hash(text)}_{source_channel}"

        for word in words:
            if self._should_skip(word):
                continue

            candidate = self._get_or_create_candidate(word, source_channel)
            candidate.occurrence_count += 1
            # Store (message_id, full_text) tuple for independent sample tracking
            candidate.contexts.append((message_id, text))
            candidate.updated_at = datetime.utcnow()

            # Check state transitions
            old_status = candidate.status
            trigger_msg_id = self._check_state_transition(candidate, message_id)

            if candidate.status != old_status:
                # FR-SLANG-03: Record which message triggered validation
                if old_status == 'LIKELY' and candidate.status == 'LIKELY':
                    # Already LIKELY, this is just incrementing count - don't update trigger
                    pass
                elif trigger_msg_id:
                    candidate.validation_trigger_msg_id = trigger_msg_id
                discovered.append(candidate)
                logger.info(f"Slang candidate {word} transitioned: {old_status} -> {candidate.status}")

        return discovered

    def _extract_words(self, text: str) -> List[str]:
        """Extract potential slang words from text."""
        # Extract words that are:
        # - 2-8 characters
        # - Not purely numbers
        # - Not already known
        import re
        words = re.findall(r'[一-鿿]{2,8}', text)
        return [w for w in words if not w.isdigit()]

    def _should_skip(self, word: str) -> bool:
        """Check if word should be skipped."""
        if word in self._known_words:
            return True
        if word in self._candidates:
            candidate = self._candidates[word]
            if candidate.status == 'REJECTED':
                if candidate.reject_until and datetime.utcnow() < candidate.reject_until:
                    return True
        return False

    def _get_or_create_candidate(self, word: str, source_channel: str = None) -> SlangCandidate:
        """Get or create a candidate entry."""
        if word not in self._candidates:
            self._candidates[word] = SlangCandidate(
                word=word,
                source_channel=source_channel
            )
        return self._candidates[word]

    def _get_context(self, text: str, word: str) -> str:
        """Get context around the word - store full original text for LLM validation."""
        return text  # 返回完整原始句子，供后续 LLM 验证使用

    def _check_state_transition(self, candidate: SlangCandidate, message_id: str = None) -> Optional[str]:
        """
        Check and execute state transitions based on count.

        Returns:
            message_id that triggered LIKELY->CONFIRMED transition (for FR-SLANG-03 tracking), else None
        """
        status = candidate.status
        count = candidate.occurrence_count
        trigger_msg_id = None

        if status == 'NEW' and count >= self.thresholds['new_to_observed']:
            candidate.status = 'OBSERVED'
            candidate.inference_count = 1

        elif status == 'OBSERVED' and count >= self.thresholds['observed_to_likely']:
            candidate.status = 'LIKELY'
            candidate.inference_count = 2

        elif status == 'LIKELY' and count >= self.thresholds['likely_to_confirmed']:
            # FR-SLANG-03: Record trigger message for independent sample exclusion
            trigger_msg_id = message_id

        elif status == 'CONFIRMED' and count >= self.thresholds['stable_count']:
            candidate.status = 'STABLE'

        return trigger_msg_id

    def _get_context(self, text: str, word: str) -> str:
        """Get context around the word - store full original text for LLM validation."""
        return text  # 返回完整原始句子，供后续 LLM 验证使用

    async def _validate_candidate_with_llm(self, candidate: SlangCandidate) -> bool:
        """
        LLM验证候选词（FR-SLANG-03 独立样本原则）：

        1. 排除触发消息（M1），使用其他独立消息作为正例
        2. 调用 LLM 生成 regex_pattern + test_cases
        3. 测试正例应匹配，负例应不匹配
        4. 返回验证结果
        """
        import os
        import json
        import re
        from openai import AsyncOpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
        model = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

        client = AsyncOpenAI(api_key=api_key, base_url=api_base)

        # FR-SLANG-03: 独立样本原则 - 排除触发验证的消息
        # contexts 存储的是 (message_id, full_text) 元组
        trigger_msg_id = candidate.validation_trigger_msg_id
        independent_contexts = [
            text for msg_id, text in candidate.contexts
            if msg_id != trigger_msg_id
        ]

        # 取最多10条独立上下文
        contexts_sample = independent_contexts[-10:] if independent_contexts else []

        if not contexts_sample:
            logger.warning(f"No independent contexts for slang candidate: {candidate.word}")
            return False

        prompt = f"""分析以下黑话候选词的含义并生成验证规则：

候选词: {candidate.word}

完整例句（来自独立的消息样本，非触发源）：
{chr(10).join(f"{i+1}. {ctx}" for i, ctx in enumerate(contexts_sample))}

请返回 JSON 格式：
{{
    "meaning": "该词的含义解释",
    "regex_pattern": "正则表达式模式",
    "test_positive_cases": ["应匹配的例1", "应匹配的例2"],
    "test_negative_cases": ["不应匹配的例1", "不应匹配的例2"],
    "is_valid_slang": true/false
}}

要求：
- regex_pattern 能匹配正例但不匹配负例
- 如果不是有效黑话，set is_valid_slang to false
- 提供的例句中包含该词的完整上下文，请结合上下文分析"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                timeout=120
            )
            result_text = response.choices[0].message.content

            # 解析 JSON 结果
            result = json.loads(result_text)

            if not result.get('is_valid_slang', False):
                logger.info(f"LLM rejected slang candidate: {candidate.word}")
                return False

            # 保存 regex_pattern
            candidate.regex_pattern = result.get('regex_pattern')
            candidate.meaning = result.get('meaning')

            # 验证 regex_pattern
            positive_cases = result.get('test_positive_cases', [])
            negative_cases = result.get('test_negative_cases', [])

            # 测试正例应该匹配
            for pos_case in positive_cases:
                if not re.search(candidate.regex_pattern, pos_case):
                    logger.warning(f"Positive case not matched: {pos_case}")
                    return False

            # 测试负例不应该匹配
            for neg_case in negative_cases:
                if re.search(candidate.regex_pattern, neg_case):
                    logger.warning(f"Negative case matched (should not): {neg_case}")
                    return False

            logger.info(f"LLM validated slang candidate: {candidate.word} -> {candidate.meaning}")
            return True

        except Exception as e:
            logger.error(f"LLM validation failed for {candidate.word}: {e}")
            return False

    async def validate_pending_candidates(self, batch_size: int = 10) -> List[SlangCandidate]:
        """
        批量验证待审核的候选词（LIKELY 状态且达到阈值）
        """
        pending = [c for c in self._candidates.values()
                   if c.status == 'LIKELY'
                   and c.occurrence_count >= self.thresholds['likely_to_confirmed']
                   and c.regex_pattern is None
                   ][:batch_size]

        confirmed = []
        for candidate in pending:
            if await self._validate_candidate_with_llm(candidate):
                candidate.status = 'CONFIRMED'
                self._known_words.add(candidate.word)
                confirmed.append(candidate)
                logger.info(f"CONFIRMED slang: {candidate.word} -> {candidate.meaning}")
            else:
                candidate.inference_count += 1
                if candidate.inference_count >= self.reject_config['max_retries']:
                    candidate.status = 'REJECTED'
                    candidate.reject_until = datetime.utcnow() + timedelta(
                        days=self.reject_config['silence_days']
                    )

        return confirmed

    def get_pending_validation(self) -> List[SlangCandidate]:
        """Get candidates that need LLM inference."""
        return [
            c for c in self._candidates.values()
            if c.status in ('OBSERVED', 'LIKELY') and c.inference_count < 3
        ]

    def get_confirmed(self) -> List[SlangCandidate]:
        """Get confirmed slang candidates."""
        return [
            c for c in self._candidates.values()
            if c.status == 'CONFIRMED'
        ]

    def get_candidate_stats(self) -> Dict[str, int]:
        """Get statistics about candidates."""
        stats = defaultdict(int)
        for c in self._candidates.values():
            stats[c.status] += 1
        return dict(stats)


class SlangDictionary:
    """Manages slang dictionary with mappings."""

    def __init__(self, mappings: Dict[str, str] = None):
        self.mappings = mappings or {}
        self._ac_automaton = None  # Would use AC automaton in production

    def add_mapping(self, slang: str, meaning: str, source: str = "learned") -> None:
        """Add a slang -> meaning mapping."""
        self.mappings[slang] = meaning
        logger.info(f"Added slang mapping: {slang} -> {meaning} (source: {source})")

    def get_mapping(self, slang: str) -> Optional[str]:
        """Get meaning for slang term."""
        return self.mappings.get(slang)

    def match_in_text(self, text: str) -> List[Dict[str, str]]:
        """Find all slang matches in text."""
        matches = []
        for slang, meaning in self.mappings.items():
            if slang in text:
                matches.append({
                    'slang_raw': slang,
                    'meaning': meaning
                })
        return matches

    def export_for_ac_automaton(self) -> List[str]:
        """Export slang terms for AC automaton."""
        return list(self.mappings.keys())