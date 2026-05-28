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

        # Sample high-confidence clues
        samples = self._db.sample_high_confidence_clues(sample_rate)
        if not samples:
            logger.info("No high-confidence samples found for error book sampling")
            return 0

        logger.info(f"Error book sampling: {len(samples)} samples collected")

        judged_count = 0
        for clue in samples:
            try:
                llm_judgment = await self._llm_judge(clue)

                if llm_judgment != clue.get("risk_label_level1"):
                    self._db.insert_error_book(
                        clue_id=clue.get("clue_id"),
                        original_label=clue.get("risk_label_level1"),
                        llm_label=llm_judgment.get("label"),
                        reason=llm_judgment.get("reason", "")
                    )
                    judged_count += 1
                    logger.info(f"Error book: inconsistency found for clue {clue.get('clue_id')}")
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

            samples = []
            for row in cur.fetchall():
                samples.append({
                    'text': row['cleaned_text'],
                    'label': row['llm_label'],
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
        Call LLM to classify a single clue.
        Returns:
            Dict with keys: label, reason, confidence
        """
        from openai import AsyncOpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
        model = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

        client = AsyncOpenAI(api_key=api_key, base_url=api_base)

        prompt = f"""You are a black-market intelligence classification expert.

Analyze the following clue and classify it into one of these categories:
- 账号交易 (Account Trading)
- 诈骗引流 (Fraud Leads)
- 流量作弊 (Traffic Cheating)
- 黑产工具 (Black-market Tools)
- 未知/其他 (Unknown/Other)

Clue text: {clue.get('cleaned_text', '')}

Return JSON:
{{
    "label": "category name",
    "reason": "classification reason",
    "confidence": 0.0-1.0
}}"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                extra_body={"reasoning_effort": "low"},
                timeout=60
            )
            result_text = response.choices[0].message.content

            # Remove LLM thinking tags
            result_text = re.sub(r'<\|think_start\|>.*?<\|think_end\|>', '', result_text, flags=re.DOTALL).strip()

            # Extract JSON
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
    def sample_high_confidence_clues(sample_rate: float = 0.01, limit: int = 100) -> list:
        """Sample high-confidence clues for error book."""
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT clue_id, cleaned_text, risk_label_level1, confidence
                FROM {}.clues
                WHERE confidence >= 0.9
                ORDER BY RANDOM()
                LIMIT %(limit)s
            """).format(sql.Identifier(instance.schema)), {"limit": limit})
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
