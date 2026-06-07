"""
Error Book Sampler - FR-EVO-02
LLM-as-a-Judge async sampling from clues table.
"""
import asyncio
import logging
import os
import re
import json
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ErrorBookSampler:
    """
    LLM async sampling for high-confidence clues.
    1. Sample high-confidence clues (confidence >= 0.9)
    2. Call LLM for secondary verification
    3. Inconsistent results written to error_book table
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._db = None
        self._sample_rate = config.get("auto_evolution", {}).get("error_book", {}).get("sample_rate", 0.01)

    async def initialize(self):
        """Initialize database connection."""
        from services.database import PostgreSQLService
        self._db = PostgreSQLService.get_instance()

    async def sample_and_judge(self, sample_rate: float = 0.01) -> int:
        """
        Sample high-confidence clues and judge with LLM.

        Args:
            sample_rate: Sampling rate (default 1%)

        Returns:
            Number of inconsistencies found
        """
        if not self._db:
            await self.initialize()

        # BUG-FIX (2026-06-07): sample_high_confidence_clues is a
        # @staticmethod on PostgreSQLService, not an instance method.
        # Calling self._db.sample_high_confidence_clues(sample_rate)
        # raised AttributeError because instance doesn't carry the
        # method. Call via the class instead.
        from services.database import PostgreSQLService
        samples = PostgreSQLService.sample_high_confidence_clues(sample_rate)
        if not samples:
            logger.info("No high-confidence samples found for error book sampling")
            return 0

        logger.info(f"Error book sampling: {len(samples)} samples collected")

        # BUG-FIX (2026-06-07): normalize labels before comparison AND
        # before insert. Previous raw string comparison caused two
        # classes of false readings:
        #   (a) "账号交易" vs "账号交易 (Account Trading)" — same class
        #       recorded as an "inconsistency"
        #   (b) Both stored as separate classes in sklearn's LabelEncoder
        # Reuse Classifier._normalize_level1_label (single source of truth).
        from pipeline.classifier import Classifier

        judged_count = 0
        for clue in samples:
            try:
                llm_judgment = await self._llm_judge(clue)
                llm_label_raw = llm_judgment.get("label", "未知/其他")
                llm_label = Classifier._normalize_level1_label(llm_label_raw)
                original_label = Classifier._normalize_level1_label(clue.get("risk_label_level1", ""))

                if llm_label != original_label:
                    self._db.insert_error_book(
                        clue_id=clue.get("clue_id"),
                        original_label=original_label,
                        llm_label=llm_label,
                        reason=llm_judgment.get("reason", "")
                    )
                    judged_count += 1
                    logger.info(f"Error book: inconsistency found for clue {clue.get('clue_id')}: {original_label} -> {llm_label}")
            except Exception as e:
                logger.error(f"LLM judgment failed for clue {clue.get('clue_id')}: {e}")

        return judged_count

    async def collect_error_samples(self, limit: int = 1000) -> List[Dict]:
        """
        FR-EVO-02: Collect error book samples for retraining with weighted sample handling.
        Returns samples with sample_weight = 0.5 (Hard Examples).
        """
        if not self._db:
            await self.initialize()

        with self._db._get_cursor() as cur:
            cur.execute("""
                SELECT e.clue_id, e.original_label, e.llm_label, c.cleaned_text
                FROM antiblack.error_book e
                JOIN antiblack.clues c ON e.clue_id = c.clue_id
                WHERE e.used_for_training = FALSE
                ORDER BY e.created_at DESC
                LIMIT %(limit)s
            """, {'limit': limit})

            # BUG-FIX (2026-06-07): normalize llm_label on read so
            # sklearn's LabelEncoder gets 5 canonical classes, not the
            # polluted 7-8 it was getting before. Single source of
            # truth = Classifier._normalize_level1_label.
            #
            # BUG-FIX (2026-06-07): include clue_id in the dict —
            # the line-123 comprehension [s['clue_id'] for s in samples]
            # would KeyError without it (pre-existing bug, surfaced by
            # sub-agent review).
            from pipeline.classifier import Classifier
            samples = []
            for row in cur.fetchall():
                samples.append({
                    'clue_id': row['clue_id'],
                    'text': row['cleaned_text'],
                    'label': Classifier._normalize_level1_label(row['llm_label']),
                    'sample_weight': 0.5,
                    'label_source': 'error_book'
                })

            if samples:
                clue_ids = [s['clue_id'] for s in samples]
                cur.execute("""
                    UPDATE antiblack.error_book
                    SET used_for_training = TRUE
                    WHERE clue_id = ANY(%(clue_ids)s)
                """, {'clue_ids': clue_ids})

        logger.info(f"Collected {len(samples)} error book samples for training")
        return samples

    async def _llm_judge(self, clue: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call unified LLM client to classify a single clue.
        Returns:
            Dict with keys: label, reason, confidence
        """
        from models.clients.llm import LLMClient

        # BUG-FIX (2026-06-07): prompt rewritten to require Chinese-only
        # labels. Previous bilingual list ("账号交易 (Account Trading)")
        # let the LLM return either form, polluting sklearn's
        # LabelEncoder with duplicate class names. JSON spec now
        # explicitly forbids English / parenthetical variants.
        prompt = f"""You are a black-market intelligence classification expert.

Classify the following clue into EXACTLY ONE of these 5 labels.
Return the label VERBATIM in Chinese, with NO English, NO parenthetical,
NO translation. Just the 4-5 character Chinese name.

Labels (return ONE of these exact strings):
- 账号交易
- 流量作弊
- 诈骗引流
- 黑产工具
- 未知/其他

Clue text: {clue.get('cleaned_text', '')}

Return JSON only, with this exact shape:
{{
    "label": "<one of the 5 Chinese labels above, verbatim>",
    "reason": "<short reason, 1-2 sentences>",
    "confidence": <0.0-1.0>
}}"""

        logger.info(f"[LLM Call] Triggering Error Book LLM Judge for clue: {clue.get('clue_id')}")

        try:
            client = LLMClient(timeout=60)
            result_text = await client.complete(
                prompt=prompt,
                max_tokens=1024,
                extra_body={"reasoning_effort": "low"},
            )

            # Extract JSON (LLMClient already stripped thinking tags)
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result

            return {"label": "未知/其他", "reason": "LLM response parse failed", "confidence": 0.0}
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return {"label": "未知/其他", "reason": str(e), "confidence": 0.0}


# Database helper extension
def extend_postgres_service():
    """Extend PostgreSQLService with error book methods."""
    from services.database import PostgreSQLService
    from psycopg2 import sql
    from psycopg2.extras import Json

    if hasattr(PostgreSQLService, "sample_high_confidence_clues"):
        return

    @staticmethod
    def sample_high_confidence_clues(sample_rate: float = 0.01,
                                     min_confidence: float = 0.9,
                                     max_rows: int = 500) -> list:
        """Sample high-confidence clues for error book.

        BUG-FIX (2026-06-07): sample_rate was a decorative parameter —
        the SQL used a hardcoded LIMIT 100, so 0.01% and 100% both
        returned 100 rows. Now `WHERE RANDOM() < sample_rate` does real
        Bernoulli sampling, capped at max_rows to prevent runaway under
        burst traffic. At production rate (~32k high-conf/day) × 0.01
        we expect ~320 candidates/day.

        min_confidence MUST match the trigger threshold in
        count_recent_high_confidence_clues (services/database.py:188).
        """
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            # BUG-FIX (2026-06-07): drop ORDER BY RANDOM() — the
            # `WHERE RANDOM() < sample_rate` already provides random
            # selection, so an additional sort on RANDOM() is wasted
            # work (O(N log N) on 32k confident rows). ORDER BY
            # confidence DESC gives stable priority without sort cost.
            cur.execute(sql.SQL("""
                SELECT clue_id, cleaned_text, risk_label_level1, confidence
                FROM {}.clues
                WHERE confidence >= %(min_confidence)s
                  AND RANDOM() < %(sample_rate)s
                ORDER BY confidence DESC
                LIMIT %(max_rows)s
            """).format(sql.Identifier(instance.schema)), {
                "min_confidence": min_confidence,
                "sample_rate": sample_rate,
                "max_rows": max_rows,
            })
            return cur.fetchall()

    @staticmethod
    def insert_error_book(clue_id: str, original_label: str, llm_label: str, reason: str) -> str:
        """Insert an error book entry."""
        instance = PostgreSQLService.get_instance()

        from utils import generate_id

        error_id = generate_id("error")

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.error_book
                (error_id, clue_id, original_label, llm_label, reason, created_at)
                VALUES (%(error_id)s, %(clue_id)s, %(original_label)s, %(llm_label)s, %(reason)s, NOW())
            """).format(sql.Identifier(instance.schema)), {
                "error_id": error_id,
                "clue_id": clue_id,
                "original_label": original_label,
                "llm_label": llm_label,
                "reason": reason
            })

        return error_id

    PostgreSQLService.sample_high_confidence_clues = sample_high_confidence_clues
    PostgreSQLService.insert_error_book = insert_error_book
