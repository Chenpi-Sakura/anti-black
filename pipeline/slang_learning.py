"""
Slang Learning module for AntiBlack pipeline.
Handles automatic discovery and learning of new slang terms.
"""
import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

import emoji
from openai import AsyncOpenAI

from config.slang_blacklist import is_blacklisted

logger = logging.getLogger(__name__)


# Module-level singleton executor for ReDoS-safe regex matching.
# Reused across all calls to avoid the cost of creating/tearing down a
# thread pool on every backtest iteration (40+ times per candidate).
_REDOS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="redos_guard"
)
atexit.register(_REDOS_EXECUTOR.shutdown, wait=False)


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

    def __init__(self, config: Dict[str, Any], slang_mappings: Dict[str, str] = None,
                 db_service: Optional[Any] = None):
        self.config = config
        self.slang_mappings = slang_mappings or {}
        # Optional injected DB service; falls back to PostgreSQLService.get_instance()
        # at use time so callers that don't pre-wire the dependency still work.
        self._db_service = db_service

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

        # Elimination & backtest thresholds (slang_learning.elimination.*)
        elim = slang_config.get('elimination', {})
        self.elimination = {
            'min_occurrences': elim.get('min_occurrences', 200),
            'min_hit_rate': elim.get('min_hit_rate', 0.05),
            'backtest_threshold': elim.get('backtest_threshold', 0.6),
            # 0.5s per regex match: 40 backtest items => <=20s ceiling.
            # Bumping this above 1s is unsafe in production.
            'backtest_timeout_seconds': elim.get('backtest_timeout_seconds', 0.5),
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
        from models import SlangStatus

        try:
            db = PostgreSQLService.get_instance()
            db_candidates = db.get_slang_candidates_by_status(SlangStatus.NEW)
            db_candidates.extend(db.get_slang_candidates_by_status(SlangStatus.OBSERVED))
            db_candidates.extend(db.get_slang_candidates_by_status(SlangStatus.LIKELY))
            # FR-SLANG-03 + 末位淘汰: also load REJECTED with their reject_until
            # so the silence-period check in _should_skip survives daemon restarts.
            db_candidates.extend(db.get_slang_candidates_by_status(SlangStatus.REJECTED))

            for db_c in db_candidates:
                word = db_c.get('candidate_word', '')
                if word and word not in self._candidates:
                    reject_until_raw = db_c.get('reject_until')
                    reject_until = None
                    if reject_until_raw:
                        if isinstance(reject_until_raw, datetime):
                            reject_until = reject_until_raw
                        elif isinstance(reject_until_raw, str):
                            try:
                                reject_until = datetime.fromisoformat(reject_until_raw)
                            except ValueError:
                                reject_until = None

                    # BUG-FIX (2026-06-08): restore contexts from JSONB column.
                    # _persist_candidate stores contexts as List[str] (text only,
                    # msg_id stripped). The validator iterates
                    #   [text for msg_id, text in candidate.contexts
                    #    if msg_id != trigger_msg_id]
                    # so we reconstruct (synthetic_msg_id, text) tuples.
                    # Synthetic msg_id = hash(text) so identical texts collapse
                    # (matches process_text's fallback at
                    # pipeline/slang_learning.py:202-203). Without this fix,
                    # daemon restart zeros all contexts and validation fails
                    # with layer='no_contexts' on every revived candidate.
                    raw_contexts = db_c.get('contexts') or []
                    source_channel = db_c.get('source_channel') or 'unknown'
                    restored_contexts = [
                        (f"{hash(text)}_{source_channel}", text)
                        for text in raw_contexts
                        if isinstance(text, str) and text
                    ]

                    self._candidates[word] = SlangCandidate(
                        word=word,
                        contexts=restored_contexts,
                        occurrence_count=db_c.get('occurrence_count', 0),
                        status=db_c.get('status', 'NEW'),
                        inference_count=db_c.get('inference_count', 0),
                        reject_until=reject_until,
                        regex_pattern=db_c.get('regex_pattern'),
                        meaning=db_c.get('meaning'),
                        source_channel=source_channel
                    )

            if self._candidates:
                logger.info(f"Loaded {len(self._candidates)} slang candidates from database")
        except Exception as e:
            logger.warning(f"Failed to load candidates from DB: {e}")

    def _persist_candidate(self, candidate: SlangCandidate):
        """Persist candidate to database."""
        from services.database import PostgreSQLService
        from models import SlangCandidate as DBSlangCandidate

        try:
            db = PostgreSQLService.get_instance()
            db_candidate = DBSlangCandidate(
                candidate_word=candidate.word,
                contexts=[text for _, text in candidate.contexts],
                occurrence_count=candidate.occurrence_count,
                status=candidate.status,
                inference_count=candidate.inference_count,
                reject_until=candidate.reject_until,
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
            is_newly_created = candidate.occurrence_count == 0
            candidate.occurrence_count += 1
            # Store (message_id, full_text) tuple for independent sample tracking
            candidate.contexts.append((message_id, text))
            candidate.updated_at = datetime.utcnow()

            # BUG-FIX (2026-06-07): previously, _persist_candidate was
            # only called on STATE TRANSITION. That meant a NEW
            # candidate sitting in self._candidates with occurrence
            # count 1 was never written to DB, and a daemon restart
            # would lose it (the next process_text call would
            # re-discover the same word and create a fresh in-memory
            # entry, but contexts and trigger_msg_id would be lost).
            # Now: persist any newly-created candidate immediately,
            # then persist again on every state transition below.
            if is_newly_created:
                self._persist_candidate(candidate)

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
        """Extract potential slang words from text.

        Three paths, deduplicated, all gated by `is_blacklisted` (TTL-aware):
          A) jieba CJK tokenization (1-gram + adjacent 2-gram) — primary path for CJK
          B) Emoji-adjacent sliding window — captures '加微💰', '出号😈', 'v🔞', '👩‍💻代练'
          C) emoji.distinct_emoji_list — pure emoji & ZWJ composites jieba/regex miss

        Length is bounded at 1-8 codepoints. Single-char tokens are only
        accepted when they are an emoji (single CJK chars are too noisy).
        """
        _CJK = re.compile(r'[一-鿿぀-ゟ가-힯]')
        _PUNCT_HAS = re.compile(r'[.,;:?!，。、；：？！]')
        _PUNCT_TRIM = re.compile(r'^[.,;:?!，。、；：？！\s]+|[.,;:?!，。、；：？！\s]+$')

        candidates: List[str] = []
        seen: Set[str] = set()

        def is_valid(w: str) -> bool:
            if not w or w.isdigit():
                return False
            if _PUNCT_HAS.search(w):
                return False
            # Pure ASCII alpha must be >= 3 chars (avoid "ab" noise)
            try:
                if w.encode('utf-8').isalpha() and len(w) < 3:
                    return False
            except UnicodeEncodeError:
                pass
            n = len(w)
            if n == 1:
                return emoji.is_emoji(w)
            if n > 8:
                return False
            # Must contain CJK or at least one emoji codepoint
            if not (_CJK.search(w) or any(emoji.is_emoji(c) for c in w)):
                return False
            if is_blacklisted(w):
                return False
            # BUG-FIX (2026-06-07): stopword filter for high-frequency daily
            # phrases (我尝试/话说/羡慕/你建议/买手机/一直在/努力).
            # Without this, 27k LIKELY pool is mostly daily phrases and
            # each LLM rejection costs 5-15s. O(1) Set lookup.
            try:
                from config.slang_stopwords import is_stopword
                if is_stopword(w):
                    return False
            except ImportError:
                pass
            return True

        def add(w: str) -> None:
            if not w:
                return
            w = _PUNCT_TRIM.sub('', w)
            if is_valid(w) and w not in seen:
                candidates.append(w)
                seen.add(w)

        # === Path A: jieba CJK tokenization ===
        try:
            import jieba
            toks = list(jieba.cut(text))
            for i, t in enumerate(toks):
                add(t)
                if i + 1 < len(toks):
                    add(t + toks[i + 1])
        except ImportError:
            for m in re.finditer(r'[一-鿿]{2,8}', text):
                add(m.group(0))

        # === Path B: emoji-adjacent sliding window ===
        # For each emoji cluster, extend up to 4 CJK / ASCII-letter chars on each
        # side, then emit every (left_n, right_n) sub-window containing the cluster.
        n = len(text)
        i = 0
        while i < n:
            if emoji.is_emoji(text[i]):
                # Greedy join trailing ZWJ / VS16 / chained emoji into one cluster
                j = i + 1
                while j < n and (
                    text[j] in '‍️'
                    or (text[j - 1] == '‍' and emoji.is_emoji(text[j]))
                ):
                    j += 1
                cluster = text[i:j]
                # Left context (up to 4 chars of CJK or ASCII letter)
                l_start = i
                while (
                    l_start > 0
                    and i - l_start < 4
                    and (_CJK.match(text[l_start - 1]) or text[l_start - 1].isalpha())
                ):
                    l_start -= 1
                # Right context (up to 4 chars)
                r_end = j
                while (
                    r_end < n
                    and r_end - j < 4
                    and (_CJK.match(text[r_end]) or text[r_end].isalpha())
                ):
                    r_end += 1
                left = text[l_start:i]
                right = text[j:r_end]
                for ll in range(len(left) + 1):
                    for rr in range(len(right) + 1):
                        add(left[len(left) - ll:] + cluster + right[:rr])
                i = j
            else:
                i += 1

        # === Path C: pure emoji & ZWJ composites the other paths miss ===
        for cluster in emoji.distinct_emoji_list(text):
            add(cluster)

        return candidates

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

        # BUG-FIX (2026-06-07): per-message distinctness guard. Phrases
        # like "合适的话我就收了" can have 20 occurrences all from 2-3
        # messages (people copy-paste), inflating occurrence_count
        # without real diversity. Require >= 5 distinct message_ids
        # to advance to LIKELY. REJECTED/LIKELY/CONFIRMED stay as-is.
        def _distinct_msg_count() -> int:
            if not candidate.contexts:
                return 0
            return len({mid for mid, _ in candidate.contexts if mid is not None})

        if status == 'NEW' and count >= self.thresholds['new_to_observed']:
            if _distinct_msg_count() < 3:
                return None
            candidate.status = 'OBSERVED'
            candidate.inference_count = 1

        elif status == 'OBSERVED' and count >= self.thresholds['observed_to_likely']:
            if _distinct_msg_count() < 5:
                return None
            candidate.status = 'LIKELY'
            candidate.inference_count = 2

        elif status == 'LIKELY' and count >= self.thresholds['likely_to_confirmed']:
            # FR-SLANG-03: Record trigger message for independent sample exclusion
            trigger_msg_id = message_id

        elif status == 'CONFIRMED' and count >= self.thresholds['stable_count']:
            candidate.status = 'STABLE'

        return trigger_msg_id

    @staticmethod
    def _is_redos_unsafe(pattern: str) -> bool:
        """
        Heuristic ReDoS detector: reject patterns exhibiting classic catastrophic
        backtracking structure. This is the PRIMARY defense — `concurrent.futures`
        timeout is a fallback only, because CPython's `_sre` C extension does NOT
        release the GIL during search, so a worker stuck in `re.search` cannot
        be interrupted by the main thread's `future.result(timeout=...)`.

        Heuristics (covers the common catastrophic cases):
        1. Nested quantifier: a quantified group whose body contains a quantifier.
           e.g. (a+)+  (.*)+  (\w+)*  (a|a)+
        2. Adjacent quantifiers on the same atom: a++  a**  a+*  a*+
        3. Quantified alternation: (a|b)+  (foo|bar)*  (a|aa)+
           Conservative — may flag some safe alternations, but cheap insurance
           against the LLM emitting overlapping-prefix alternatives.
        """
        # 1) Nested quantifier: (...)+ or (...)* where the body has a quantifier
        if re.search(r'\([^?+*][^()]*[+*][^()]*\)[+*]', pattern):
            return True
        # 2) Adjacent quantifiers on the same atom
        if re.search(r'[+*][+*]', pattern):
            return True
        # 3) Quantified alternation: (alt)+
        if re.search(r'\([^()]*\|[^()]*\)[+*]', pattern):
            return True
        return False

    @staticmethod
    def _safe_regex_search(pattern: str, text: str, timeout: float) -> Optional[re.Match]:
        """
        ReDoS-safe regex search. Layers:
        1. Compile + heuristic ReDoS pattern check (cheap, primary defense).
        2. Submit to module-level worker pool with timeout (defense in depth,
           only effective when the C engine yields — see `_is_redos_unsafe`).
        Returns None on compile error, ReDoS-unsafe pattern, or timeout.
        """
        if SlangLearner._is_redos_unsafe(pattern):
            logger.warning(f"ReDoS-unsafe pattern rejected: {pattern[:80]}")
            return None
        try:
            compiled = re.compile(pattern)
        except re.error:
            return None
        future = _REDOS_EXECUTOR.submit(compiled.search, text)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return None
        except re.error:
            return None

    async def _collect_contexts_from_clues(self, word: str, limit: int = 30) -> list[str]:
        """从 clues 表实时收集候选词上下文（替代 JSONB contexts）。

        每次 validation 时按 created_at DESC 取最近 N 条 cleaned_text。
        源头在 clues 表，不怕 daemon 重启、REJECT/un-reject 循环覆盖。

        statement_timeout=5s 防极端高频词拖慢查询。
        """
        from services.database import PostgreSQLService
        db = PostgreSQLService.get_instance()

        def _fetch() -> list[str]:
            with db._get_cursor() as cur:
                try:
                    cur.execute("SET LOCAL statement_timeout = 5000")
                except Exception:
                    pass
                try:
                    cur.execute("""
                        SELECT cleaned_text
                        FROM antiblack.clues
                        WHERE cleaned_text LIKE %s
                          AND cleaned_text IS NOT NULL
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (f"%{word}%", limit))
                    return [r['cleaned_text'] for r in cur.fetchall()]
                except Exception as e:
                    logger.warning(f"Failed to collect contexts for '{word}': {e}")
                    return []

        return await asyncio.to_thread(_fetch)

    async def _validate_candidate_with_llm(self, candidate: SlangCandidate) -> tuple[bool, str]:
        """
        LLM验证候选词（FR-SLANG-03 独立样本原则）：

        Returns:
            (success, reason): reason is "" on success, "<layer>:<details>"
            on failure. Layer values: "no_contexts", "json_parse",
            "llm_self_report", "llm_no_regex", "pos_case_miss",
            "neg_case_hit", "meaning_inconsistent", "backtest_low",
            "exception".

        所有 `re.search` 均走 `_safe_regex_search`，防止大模型返回的灾难性
        回溯正则卡死事件循环。
        """
        from models.clients.llm import LLMClient
        client = LLMClient(timeout=120, max_retries=0)

        logger.info(f"[LLM Call] Triggering Slang Validation for candidate: '{candidate.word}'")

        # BUG-FIX (2026-06-08): 从 clues 表实时拉 contexts，不再依赖
        # candidate.contexts（JSONB 列在 daemon 重启/REJECT 循环中会被
        # 清空）。每次 validation 取最近 30 条 cleaned_text。
        all_contexts = await self._collect_contexts_from_clues(candidate.word, limit=30)
        if not all_contexts:
            logger.warning(f"No contexts found in clues for '{candidate.word}'")
            return (False, "no_contexts_in_clues")

        # 前 10 条发给 LLM 做 prompt context，后面做 backtest
        contexts_sample = all_contexts[:10]
        backtest_contexts = all_contexts[10:] if len(all_contexts) > 10 else []

        # ---- 三段式 Prompt：人设 + 核心防误判 + 对抗性样本 ----
        prompt = f"""你是一个顶级的【黑产风控情报专家】。本系统聚焦【字节跳动旗下产品的黑灰产业】（抖音 / TikTok / 头条 / 西瓜 / 飞书 / 豆包 / 剪映 等）。你的任务是鉴定给定的词汇是否为字节系黑产（如账号买卖、刷量刷粉、私域引流、规避审查代称）发明的【专属暗语/代称/行话】。

候选词: {candidate.word}

真实语料库（供你结合上下文体会其真实意图）：
{chr(10).join(f"{i+1}. {ctx}" for i, ctx in enumerate(contexts_sample))}

【核心防误判规则】（必须严格遵守，违者零分）：
1. 如果该词在语料中仅仅是"被交易的客体"或"正常名词"（如：游戏名"王者荣耀"、App名"微信"、星座名"十二星座"），它绝对不是黑话，is_valid_slang 必须为 false。
2. 如果该词是常见的日常动词/形容词（如："买卖"、"加好友"），哪怕它出现在违规帖子里，它也不是黑话。黑话必须具备"隐蔽性"或"特定圈子属性"（如："出抖号"、"音符"、"换绑即可绝不找回"）。
3. **本系统不关心非字节系游戏账号交易**（三角洲行动 / 和平精英 / 王者荣耀 等都是腾讯系），与游戏租号/代练/卖号相关的词必须 is_valid_slang=false，理由写明"非字节系业务范畴"。
4. **绝对拒绝以下类别**（不论上下文）：
   - 内容标签 / 话题标签（"原创"、"搞笑"、"日常"、"笔记"、"合集"）
   - 通用商务平台词（"合作"、"报价"、"平台"、"运营"、"开通"）
   - 用户画像（"大学生"、"甜妹"、"未成年"）
   - 文本截断碎片（如以"的"、"了"开头/结尾的不完整句子）
   - 平台官方词（"DOU+"、"蒲公英"、"闲鱼"、"抖音"）
   - 反诈宣传词（"反诈骗"、"立案调查"、"防诈骗"）

【emoji / 符号保留规则】（重要）：
- 候选词若包含 emoji（💰😈🔞👩‍💻等）或特殊符号（v/+/➗/❤️等），refined_word 和 regex_pattern **必须完整保留这些字符**，不可替换为文字描述、不可删除。
- 黑产为规避审查刻意使用 emoji/谐音/符号替代（如 "加微💰" = 加微信谈价，"音符" = 抖音平台），这些 emoji 本身就是黑话的关键组成。
- regex 用 Python re 模块语法即可（Python re 原生支持 UTF-8 emoji，无需特殊转义）。

【正则与对抗性样本规则】：
1. 正则 (regex_pattern)：必须精准，既不能硬编码无用的语气词，也不能过度泛化导致误杀正常语句。
2. 正例 (test_positive_cases)：造 2 个【字节系】黑产语境的短句，必须能被你的正则匹配。
3. 对抗性负例 (test_negative_cases)：造 2 个【包含该候选词核心字眼，但语境完全日常、合法】的短句！例如，如果候选词是"种草"，负例必须是"我在阳台种草"，绝不能用"今天天气很好"这种毫无关联的废话。你的正则绝对不能匹配这两个负例！
4. **【正则负例绝对不能匹配】** 你生成的 regex_pattern 绝对不能在任何一条 test_negative_cases 上产生匹配。注意：中文环境下绝对不要使用 \\b (词边界)！因为 Python re 中 \\b 匹配的是单词字符与非单词字符的边界，而中文字符全部属于单词字符，词边界在中文中完全无效。对于极短的通用词（如"出个"/"一半"），请将周围的交易动作、物品属性也写进正则（例如 出个.*(?:号|粉|千) 或 (?:抖音|头条).*出个），确保纯日常语境被彻底排除。

请严格返回 JSON 格式（不要包含 markdown 代码块标记）：
{{
    "refined_word": "修正后的黑话词汇本体（含 emoji/符号，与候选词一致或仅修正错别字）",
    "meaning": "该词在字节系黑产场景下的含义解释",
    "regex_pattern": "Python re 正则模式（保留 emoji/符号原貌）",
    "test_positive_cases": ["字节系黑产语境正例1", "字节系黑产语境正例2"],
    "test_negative_cases": ["含候选词字眼但日常合法的负例1", "含候选词字眼但日常合法的负例2"],
    "is_valid_slang": true/false
}}"""

        try:
            result_text = await client.complete(
                prompt=prompt,
                max_tokens=8192,
                extra_body={"reasoning_effort": "low"},
            )

            logger.info(f"LLM raw response for {candidate.word}: {result_text[:500]}")

            # 提取 JSON 块（支持 ```json ... ``` 或直接 JSON）
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(1)
            else:
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
                return (False, f"json_parse:{e}")

            # 5. 半跳过策略（2026-06-08）：LLM 判 true 则直接通过，
            #    但必须先过负例防误杀闸门。
            #
            #    策略：
            #    - LLM is_valid_slang=true  → 跳过 60% 正例命中率要求，
            #                                   只验证正例应匹配（regex 没写错）
            #                                   + 负例不应匹配（防宽泛正则误杀）
            #    - LLM is_valid_slang=false → 保留完整 backtest 兜底
            #
            #    核心保底：eliminate_weak_slangs() 在 200 occ +
            #    <5% 命中率时会召回，但宽泛 regex 可能在召回前
            #    已造成大量误杀。因此 negative case 检查是硬性
            #    要求，绝不跳过。
            llm_says_slang = result.get('is_valid_slang', False)

            # 保存 regex_pattern
            candidate.regex_pattern = result.get('regex_pattern')
            candidate.meaning = result.get('meaning')
            refined_word = result.get('refined_word')
            if refined_word and refined_word != candidate.word and len(refined_word) >= 2:
                logger.info(f"LLM refined candidate word from '{candidate.word}' to '{refined_word}'")
                candidate.word = refined_word

            if not candidate.regex_pattern:
                logger.warning(f"LLM returned no regex_pattern for {candidate.word}")
                # 即使无 regex，LLM 判 slang 且有 meaning 也放行
                if llm_says_slang and candidate.meaning:
                    logger.info(f"LLM says slang, has meaning, passing without regex: {candidate.word}")
                    return (True, "")
                return (False, "llm_no_regex")

            # ---- 验证 LLM 自造的正例（应匹配）/负例（应不匹配） ----
            positive_cases = result.get('test_positive_cases', [])
            negative_cases = result.get('test_negative_cases', [])
            timeout_s = self.elimination['backtest_timeout_seconds']

            # 正例检查：regex 必须能匹配至少 1 个 LLM 自造的正例
            if positive_cases:
                pos_matched = 0
                for pos_case in positive_cases:
                    if self._safe_regex_search(candidate.regex_pattern, pos_case, timeout_s) is not None:
                        pos_matched += 1
                if pos_matched == 0:
                    logger.warning(f"All positive cases unmatched for {candidate.word}")
                    return (False, "pos_case_all_miss")

            # 负例检查：绝不放行（无论 LLM 判 slang 或 not-slang）
            # 这是防宽泛 regex 误杀的最后防线
            for neg_case in negative_cases:
                if self._safe_regex_search(candidate.regex_pattern, neg_case, timeout_s) is not None:
                    logger.warning(f"Negative case matched (should not): {neg_case}")
                    return (False, f"neg_case_hit:{neg_case[:40]}")

            logger.info(f"LLM self-test passed for {candidate.word} -> {candidate.meaning}")

            # LLM 自报=true：跳过正例命中率要求和 backtest，直接通过
            if llm_says_slang:
                logger.info(f"LLM confirmed slang: {candidate.word} -> {candidate.meaning}")
                return (True, "")

            # LLM 自报=false 时才走完整 backtest（advisory 兜底）
            logger.info(
                f"LLM self-reported not-slang (advisory, will still backtest): "
                f"{candidate.word}"
            )

            for pos_case in positive_cases:
                if self._safe_regex_search(candidate.regex_pattern, pos_case, timeout_s) is None:
                    logger.warning(f"Positive case not matched: {pos_case[:30]}")
                    return (False, f"pos_case_miss:{pos_case[:40]}")

            for neg_case in negative_cases:
                if self._safe_regex_search(candidate.regex_pattern, neg_case, timeout_s) is not None:
                    logger.warning(f"Negative case matched (should not): {neg_case}")
                    return (False, f"neg_case_hit:{neg_case[:40]}")

            logger.info(f"LLM self-test passed for {candidate.word} -> {candidate.meaning}")

            # FR-SLANG-04: 释义一致性验证
            if len(contexts_sample) >= 2:
                if not self._check_meaning_consistency(candidate.meaning, contexts_sample):
                    logger.info(f"Meaning inconsistent for {candidate.word}, downgrading to OBSERVED")
                    candidate.status = 'OBSERVED'
                    return (False, "meaning_inconsistent")

            # ---- 真实回测：剩余 held-out 上下文 ----
            # backtest_contexts 已在上面从 all_contexts[10:] 分好
            if backtest_contexts:
                threshold = self.elimination['backtest_threshold']
                matched = 0
                for ctx in backtest_contexts:
                    m = await asyncio.to_thread(
                        self._safe_regex_search, candidate.regex_pattern, ctx, timeout_s
                    )
                    if m is not None:
                        matched += 1
                rate = matched / len(backtest_contexts)
                if rate < threshold:
                    logger.warning(
                        f"Backtest failed for '{candidate.word}': "
                        f"{matched}/{len(backtest_contexts)} ({rate:.1%}) < {threshold:.0%}. Rejecting."
                    )
                    return (False, f"backtest_low:{matched}/{len(backtest_contexts)}={rate:.1%}<{threshold:.0%}")
                logger.info(
                    f"Backtest passed for '{candidate.word}': "
                    f"{matched}/{len(backtest_contexts)} ({rate:.1%})"
                )

            return (True, "")

        except Exception as e:
            logger.error(f"LLM validation failed for {candidate.word}: {e}")
            # 不再降级到 regex_fallback：按计划彻底删除兜底。
            # 失败由 validate_pending_candidates 的 retry 计数接管。
            return (False, f"exception:{type(e).__name__}:{e}")

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

    async def validate_pending_candidates(
        self,
        batch_size: int = 200,
        concurrency: int = 4,
        pacing_sec: float = 1.0,
    ) -> List[SlangCandidate]:
        """
        批量验证待审核的候选词（LIKELY 状态且达到阈值）。

        Concurrency model (2026-06-06 调优):
          - batch_size=200: 一次从 27k LIKELY 池里取 200 个
          - concurrency=4: 同时最多 4 个 LLM 请求在飞
          - pacing_sec=1.0: 每 1s 启一个新任务（rate-limit-friendly）

        之前默认 batch_size=30 + 完全串行 = 30/h。新配置下稳态吞吐:
          4 并发 × 13s/任务 / (1s pacing) ≈ 4/13 = 0.31/s 但 pacing 是真节流
          → 实际 ~1 candidate/s = 3600/h, 提速 120x。
        27k LIKELY 预计 7-8 天消化完（vs 之前 37 天）。

        Three-layer gate (FR-SLANG-03) 仍在 _validate_candidate_with_llm 内
        严格执行, batch_size 增大不降低验证严格度。
        """
        # BUG-FIX (2026-06-08): sort by occurrence_count DESC so the
        # highest-count candidates (most likely real slangs, including
        # revived ones) get processed first. Without sort, dict-insertion
        # order leaves recently-added/revived candidates at the tail of
        # the queue, where the batch_size=200 slice never reaches them.
        # LLM is a per-call cost, so highest-count-first maximizes the
        # value of each validation cycle.
        eligible = [c for c in self._candidates.values()
                    if c.status == 'LIKELY'
                    and c.occurrence_count >= self.thresholds['likely_to_confirmed']
                    and c.regex_pattern is None]
        eligible.sort(key=lambda c: c.occurrence_count, reverse=True)
        pending = eligible[:batch_size]

        if not pending:
            return []

        sem = asyncio.Semaphore(concurrency)
        launch_lock = asyncio.Lock()
        last_launch = [0.0]  # mutable container for closure

        async def _validate_with_limit(candidate):
            # Pacing: ensure pacing_sec between task launches
            async with launch_lock:
                now = time.monotonic()
                wait = pacing_sec - (now - last_launch[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                last_launch[0] = time.monotonic()
            # Concurrency cap: max N in-flight at once
            async with sem:
                return await self._validate_candidate_with_llm(candidate), candidate

        # Launch all batch_size tasks; they self-pace via launch_lock
        tasks = [asyncio.create_task(_validate_with_limit(c)) for c in pending]
        # BUG-FIX (2026-06-07, CR #6): return_exceptions=True so one failed
        # validation doesn't cancel siblings (e.g. transient LLM 429 cascade
        # would otherwise wipe the whole batch).
        results = await asyncio.gather(*tasks, return_exceptions=True)

        confirmed = []
        layer_failure_counts: Dict[str, int] = {}  # layer -> count (one cycle)
        for r in results:
            if isinstance(r, Exception):
                # CR #6: sibling failure surfaced as Exception; skip but don't
                # re-raise so the rest of the batch completes.
                logger.warning(f"Slang validation task raised: {r}")
                continue
            (success, reason), candidate = r
            if success:
                candidate.status = 'CONFIRMED'
                self._known_words.add(candidate.word)
                self._persist_candidate(candidate)
                confirmado.append(candidate)
                logger.info(f"CONFIRMED slang: {candidate.word} -> {candidate.meaning}")
            else:
                # Layer = first segment of "layer:details" reason string
                layer = reason.split(":", 1)[0] if reason else "unknown"
                layer_failure_counts[layer] = layer_failure_counts.get(layer, 0) + 1
                logger.info(
                    f"Slang validation failed: candidate='{candidate.word}' "
                    f"layer={layer} reason={reason}"
                )
                candidate.inference_count += 1
                if candidate.inference_count >= self.reject_config['max_retries']:
                    candidate.status = 'REJECTED'
                    candidate.reject_until = datetime.utcnow() + timedelta(
                        days=self.reject_config['silence_days']
                    )
                    # 持久化 REJECTED 状态 + reject_until，保证 daemon
                    # 重启后 _should_skip 仍能识别沉默期。
                    self._persist_candidate(candidate)
                    logger.info(
                        f"REJECTED slang: {candidate.word} (silenced until {candidate.reject_until})"
                    )

        if layer_failure_counts:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(layer_failure_counts.items(), key=lambda x: -x[1]))
            logger.info(f"Validation layer failure summary (this cycle): {summary}")

        return confirmed

    async def eliminate_weak_slangs(self) -> int:
        """
        末位淘汰：把出现次数 ≥min_occurrences 且命中率 <min_hit_rate 的
        CONFIRMED/STABLE 候选词打入 REJECTED（30 天沉默）+ 硬删 slang_mappings。

        Returns:
            Number of slangs demoted in this cycle.
        """
        db = self._db_service
        if db is None:
            from services.database import PostgreSQLService
            db = PostgreSQLService.get_instance()
            self._db_service = db

        try:
            weak = db.evaluate_slang_effectiveness(
                min_occurrences=self.elimination['min_occurrences'],
                min_hit_rate=self.elimination['min_hit_rate'],
            )
        except Exception as e:
            logger.error(f"evaluate_slang_effectiveness failed: {e}")
            return 0

        if not weak:
            logger.info("No weak slangs to eliminate this cycle.")
            return 0

        words = [r['candidate_word'] for r in weak]
        try:
            db.demote_slangs(words)
        except Exception as e:
            logger.error(f"demote_slangs failed for {len(words)} candidates: {e}")
            return 0

        # 同步本地状态：in-memory 候选词置为 REJECTED + 沉默期，
        # 保证后续 process_text 的 _should_skip 立刻生效。
        now = datetime.utcnow()
        reject_until = now + timedelta(days=self.reject_config['silence_days'])
        for word in words:
            if word in self._candidates:
                cand = self._candidates[word]
                cand.status = 'REJECTED'
                cand.reject_until = reject_until
            # 不再让分类器命中该词
            self._known_words.discard(word)

        sample = ', '.join(words[:10])
        logger.info(
            f"Demoted {len(words)} weak slangs: {sample}"
            f"{'...' if len(words) > 10 else ''}"
        )

        # Seed words 降级（与 promote_seed_word 对偶）。
        # source='learned' 限定让 preset 词不被误伤。
        try:
            seed_n = db.demote_seed_word(words)
            if seed_n:
                logger.info(
                    f"Seed words demoted: {seed_n} learned seeds marked degraded"
                )
        except Exception as e:
            logger.warning(f"demote_seed_word failed for {len(words)} words: {e}")

        # Note (2026-06-03): 取消 LightRAG 清理步骤。
        # 既然 slang→LightRAG 写入已在 _persist_confirmed_slang 移除，
        # 淘汰时的图谱清理也不再需要——没有节点要清。消除了 slang-to-slang
        # 的双向维护链路（写入侧 daemon_scheduler + 清理侧 slang_learning）。

        return len(words)

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

    def get_likely_count(self) -> int:
        """Count LIKELY candidates ready for LLM validation.

        Cheaper than get_candidate_stats() because it doesn't allocate
        a dict. Used by daemon's slang_evolution_loop for the
        "≥MIN_LIKELY_TO_TRIGGER?" pre-check before invoking the
        heavier validate_pending_candidates() path.
        """
        return sum(1 for c in self._candidates.values() if c.status == 'LIKELY')


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