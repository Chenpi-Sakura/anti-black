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

        # Load candidates from DB if available
        self._load_candidates_from_db()

    def _load_candidates_from_db(self):
        """Load slang candidates from database to restore state after restart."""
        from services.database import PostgreSQLService
        from models.entities import SlangStatus

        try:
            db = PostgreSQLService.get_instance()
            db_candidates = db.get_slang_candidates_by_status(SlangStatus.NEW)
            db_candidates.extend(db.get_slang_candidates_by_status(SlangStatus.OBSERVED))
            db_candidates.extend(db.get_slang_candidates_by_status(SlangStatus.LIKELY))

            for db_c in db_candidates:
                word = db_c.get('candidate_word', '')
                if word and word not in self._candidates:
                    self._candidates[word] = SlangCandidate(
                        word=word,
                        contexts=[],  # Contexts not restored, just state
                        occurrence_count=db_c.get('occurrence_count', 0),
                        status=db_c.get('status', 'NEW'),
                        inference_count=db_c.get('inference_count', 0),
                        regex_pattern=db_c.get('regex_pattern'),
                        meaning=db_c.get('meaning'),
                        source_channel=db_c.get('source_channel')
                    )

            if self._candidates:
                logger.info(f"Loaded {len(self._candidates)} slang candidates from database")
        except Exception as e:
            logger.warning(f"Failed to load candidates from DB: {e}")

    def _persist_candidate(self, candidate: SlangCandidate):
        """Persist candidate to database."""
        from services.database import PostgreSQLService
        from models.entities import SlangCandidate as DBSlangCandidate

        try:
            db = PostgreSQLService.get_instance()
            db_candidate = DBSlangCandidate(
                candidate_word=candidate.word,
                contexts=[text for _, text in candidate.contexts],
                occurrence_count=candidate.occurrence_count,
                status=candidate.status,
                inference_count=candidate.inference_count,
                regex_pattern=candidate.regex_pattern,
                meaning=candidate.meaning,
                source_channel=candidate.source_channel
            )
            db.upsert_slang_candidate(db_candidate)
        except Exception as e:
            logger.warning(f"Failed to persist candidate {candidate.word}: {e}")

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
                # Persist candidate state to DB
                self._persist_candidate(candidate)
                discovered.append(candidate)
                logger.info(f"Slang candidate {word} transitioned: {old_status} -> {candidate.status}")

        return discovered

    def _extract_words(self, text: str) -> List[str]:
        """Extract potential slang words from text."""
        # 方案二：使用 jieba 进行分词和 N-gram 抽取，解决正则硬切分问题
        try:
            import jieba
            words = list(jieba.cut(text))
            candidates = []
            
            def is_valid(w):
                import re
                # 去除两端空白和标点
                w = re.sub(r'^[.,;:?!，。、；：？！\s]+|[.,;:?!，。、；：？！\s]+$', '', w)
                if len(w) < 2 or len(w) > 8: return False
                if w.isdigit(): return False
                # 过滤包含标点符号的词汇
                if re.search(r'[.,;:?!，。、；：？！]', w): return False
                # 过滤纯英文字符组如果太短
                if w.encode('utf-8').isalpha() and len(w) < 3: return False
                return True
                
            for i, w in enumerate(words):
                # 1-gram
                import re
                clean_w = re.sub(r'^[.,;:?!，。、；：？！\s]+|[.,;:?!，。、；：？！\s]+$', '', w)
                if is_valid(clean_w):
                    candidates.append(clean_w)
                # 2-gram 组合相邻词块，防止 jieba 分词过细（如 "抖", "号"）
                if i < len(words) - 1:
                    clean_w2 = re.sub(r'^[.,;:?!，。、；：？！\s]+|[.,;:?!，。、；：？！\s]+$', '', words[i+1])
                    if clean_w and clean_w2:
                        combined = clean_w + clean_w2
                        if is_valid(combined):
                            candidates.append(combined)
            return candidates
        except ImportError:
            # Fallback
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

        prompt = f"""分析以下黑话候选词的含义，并为其生成在通用场景下的验证规则：

候选词: {candidate.word}

完整例句（仅供你理解该词的具体含义，切勿将例句中的特定前缀、后缀或无关文本写入正则）：
{chr(10).join(f"{i+1}. {ctx}" for i, ctx in enumerate(contexts_sample))}

请返回 JSON 格式：
{{
    "refined_word": "如果有截断或多余字符，请提供修正后的准确黑话词汇（否则与候选词一致）",
    "meaning": "该词的含义解释",
    "regex_pattern": "正则表达式模式",
    "test_positive_cases": ["包含该黑话的其他新造短句1", "包含该黑话的其他新造短句2"],
    "test_negative_cases": ["不包含该黑话，但字面相似的短句1", "不包含该黑话的正常句2"],
    "is_valid_slang": true/false
}}

要求：
- refined_word：如果在上下文中发现给定的候选词截取不完整，或者包含了多余的标点/语气词等，请在这里输出修正后最精炼准确的黑话词汇本体。如果没有问题，就保持与原候选词一致。
- is_valid_slang：如果该词不是有效的黑话，请设为 false。
- meaning：请结合提供的完整例句上下文，准确分析该黑话的含义。
- regex_pattern：**必须是通用匹配模式！** 目标是在任意未知文本中抓取该黑话本身。
  * ❌ 错误示范：绝对不能包含例句中特有的上下文（如标点符号、特定的开头结尾。切勿写成类似 "^【脚本引流】专业服务[a-z]*$" 的死板规则）。
  * ✅ 正确示范：如果黑话是"专业服务"，正则应该尽量精简通用，如 "专业服务" 或考虑变体的 "专\s*业\s*服\s*务"。
- test_positive_cases：**不要直接抄原例句**，请自己造两个包含该黑话的极简短句作为正例，以验证正则的通用性。
- test_negative_cases：**绝不能包含能够被 regex_pattern 字面匹配到的词汇！**
  * ⚠️极易犯错警告：正则表达式（Regex）没有语义理解能力，只认字面。如果该黑话本身也是个日常普通词汇（例如"专业服务"），**绝对不要**拿它的日常合法语境来做负例（正则必定会误杀导致测试失败）。
  * ✅正确做法：负例应该使用字面相似但不同的词汇，或者完全不相关的句子。例如黑话是"专业服务"，负例可以是"他们提供专门服务"或"这支专业团队很厉害"。
- regex_pattern 必须能正确匹配你生成的正例，且不匹配负例。"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                extra_body={"reasoning_effort": "low"},
                timeout=120
            )
            result_text = response.choices[0].message.content

            # 去除 LLM thinking tags (<think>...</think>)
            import re
            result_text = re.sub(r'<think>.*?</think>', '', result_text, flags=re.DOTALL).strip()

            logger.info(f"LLM raw response for {candidate.word}: {result_text[:500]}")

            # 提取 JSON 块（支持 ```json ... ``` 或直接 JSON）
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(1)
            else:
                # 尝试找到第一个 { 或 [ 开始的位置
                json_start = result_text.find('{')
                if json_start == -1:
                    json_start = result_text.find('[')
                if json_start > 0:
                    result_text = result_text[json_start:]

            # 解析 JSON
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse failed for {candidate.word}: {e}")
                # Step 4: 快速降级模式 - regex 仅测试
                return self._regex_fallback_validate(candidate)

            # 保存 regex_pattern
            candidate.regex_pattern = result.get('regex_pattern')
            candidate.meaning = result.get('meaning')
            refined_word = result.get('refined_word')
            if refined_word and refined_word != candidate.word and len(refined_word) >= 2:
                logger.info(f"LLM refined candidate word from '{candidate.word}' to '{refined_word}'")
                candidate.word = refined_word

            # 验证 regex_pattern
            positive_cases = result.get('test_positive_cases', [])
            negative_cases = result.get('test_negative_cases', [])

            # 测试正例应该匹配
            for pos_case in positive_cases:
                if not re.search(candidate.regex_pattern, pos_case):
                    logger.warning(f"Positive case not matched: {pos_case[:30]}")
                    # 正例不匹配时降级用 regex_fallback
                    return self._regex_fallback_validate(candidate)

            # 测试负例不应该匹配
            for neg_case in negative_cases:
                if re.search(candidate.regex_pattern, neg_case):
                    logger.warning(f"Negative case matched (should not): {neg_case}")
                    return False

            logger.info(f"LLM validated slang candidate: {candidate.word} -> {candidate.meaning}")

            # FR-SLANG-04: 释义一致性验证
            # 检查多条消息中的 meaning 是否一致（核心词相同）
            if len(contexts_sample) >= 2:
                if not self._check_meaning_consistency(candidate.meaning, contexts_sample):
                    logger.info(f"Meaning inconsistent for {candidate.word}, downgrading to OBSERVED")
                    candidate.status = 'OBSERVED'
                    return False

            return True

        except Exception as e:
            logger.error(f"LLM validation failed for {candidate.word}: {e}")
            # Step 4: 快速降级模式 - regex 仅测试
            return self._regex_fallback_validate(candidate)

    def _check_meaning_consistency(self, meaning: str, contexts: list[str]) -> bool:
        """
        FR-SLANG-04: 检查释义一致性
        通过关键词重合度判断多消息释义是否一致
        """
        import re
        # 从 meaning 提取核心词（名词/动词，2字符以上）
        core_pattern = re.compile(r'[一-龥]{2,}')
        core_words = set(core_pattern.findall(meaning))

        if not core_words:
            return True  # 无法提取核心词，跳过一致性检查

        # 检查每条上下文中是否包含核心词的关联词
        # 简化：检查 meaning 中的核心词是否在大多数上下文中被提及
        hit_count = sum(1 for ctx in contexts if any(w in ctx for w in core_words))
        hit_rate = hit_count / len(contexts) if contexts else 0

        # 核心词在 80% 以上的上下文出现，认为一致
        return hit_rate >= 0.8

    def _regex_fallback_validate(self, candidate: SlangCandidate) -> bool:
        """
        快速降级验证模式：当 LLM 调用失败时，使用 regex 覆盖度测试
        """
        import re

        # 从 contexts 提取正例（所有包含该词的上下文）
        positive_cases = [text for msg_id, text in candidate.contexts]

        if not positive_cases:
            return False

        # 简单的通用 regex：包含该词的句子
        try:
            pattern = re.compile(candidate.word)
        except re.error:
            return False

        # 检查正例是否都匹配（都应该匹配）
        matched = sum(1 for ctx in positive_cases if pattern.search(ctx))
        match_rate = matched / len(positive_cases) if positive_cases else 0

        # 80% 以上匹配率认为有效
        if match_rate >= 0.8:
            candidate.regex_pattern = candidate.word
            candidate.meaning = candidate.word  # 降级：无法确定含义时使用原词
            logger.info(f"Regex fallback validated: {candidate.word} (match_rate={match_rate:.2f})")
            return True

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