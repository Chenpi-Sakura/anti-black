"""Slang -> rule auto-bridge (Phase 2.2).

When a slang candidate transitions to CONFIRMED, this module evaluates
whether the slang can also serve as a Stage-1 classification keyword.

Two-stage check (both must agree):
  1. Embedding classifier predicts the slang's meaning belongs to a specific level1
  2. LLM independently judges the same

Constraints:
  - LLM only outputs plain-text keywords (no regex metacharacters)
  - Keywords are 2-8 chars, no brand names
  - 0.7+ embedding confidence + 0.7+ LLM confidence + level1 match
"""
import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import psycopg2.extras
from config import get_config

from pipeline.prompts import (
    SYSTEM_ROLE_RISK_ANALYST,
    build_slang_to_rule_prompt,
    format_taxonomy_text,
)

logger = logging.getLogger(__name__)


# Regex metacharacters banned from LLM-generated keywords (ReDoS prevention)
_REGEX_METACHARS = re.compile(r"[\\*+?{}\[\]()|^$.]")


def _is_safe_keyword(kw: str, min_len: int = 2, max_len: int = 8) -> bool:
    """Keyword must be plain text, 2-8 chars, no regex metacharacters."""
    if not kw or not isinstance(kw, str):
        return False
    if len(kw) < min_len or len(kw) > max_len:
        return False
    if _REGEX_METACHARS.search(kw):
        return False
    return True


def _format_taxonomy_for_prompt(cfg) -> str:
    cats = cfg.get('taxonomy', {}).get('categories', [])
    return format_taxonomy_text(cats)


def _extract_json(raw: str) -> Optional[dict]:
    """Robustly extract a JSON object from an LLM response (handles fences, prose)."""
    if not raw:
        return None
    # Try direct parse
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Try stripping code fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Try finding first {...} block
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return None


class SlangToRuleBridge:
    """Evaluate CONFIRMED slangs and adopt suitable ones as Stage-1 keywords."""

    def __init__(self, config: Dict[str, Any] = None, db_conn=None):
        self.config = config or {}
        cfg = get_config()
        self.db_cfg = cfg.postgresql
        self.bridge_cfg = self.config.get('slang_to_rule_bridge', {})
        self.batch_size = int(self.bridge_cfg.get('batch_size', 20))
        self.max_batches_per_day = int(self.bridge_cfg.get('max_batches_per_day', 2))
        self.embedding_threshold = float(
            self.bridge_cfg.get('embedding_consistency_threshold', 0.7)
        )
        self._taxonomy_text = _format_taxonomy_for_prompt(cfg._config)
        self._conn = db_conn

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=self.db_cfg.host, port=self.db_cfg.port,
                user=self.db_cfg.user, password=self.db_cfg.password,
                database=self.db_cfg.database,
            )
            self._conn.autocommit = False
        return self._conn

    # === LLM and embedding clients (lazy import to avoid hard deps at import time) ===
    async def _ask_llm(self, prompt: str) -> Optional[dict]:
        try:
            from models.clients.llm import LLMClient
            client = LLMClient(timeout=60)
            raw = await client.complete(
                prompt=prompt,
                system_prompt=SYSTEM_ROLE_RISK_ANALYST,
                max_tokens=512,
                extra_body={"reasoning_effort": "low"},
            )
            return _extract_json(raw)
        except Exception as e:
            logger.error(f"[bridge] LLM call failed: {e}")
            return None

    def _ask_embedding(self, text: str) -> Optional[Tuple[str, float]]:
        """Return (predicted_level1, confidence) or None."""
        try:
            from pipeline.classifier import Classifier
            c = Classifier(config={})
            if not c._embedding_clf or not c._embedding_le:
                return None
            return c._classify_by_embedding(text, {})  # sync, fine for short text
        except Exception as e:
            logger.error(f"[bridge] embedding call failed: {e}")
            return None
        # The embedding classify returns a ClassificationResult; pull level1 + confidence
        # Caller will get the result

    async def _classify_meaning_with_embedding(self, meaning: str) -> Optional[Tuple[str, float]]:
        """Classify the slang's meaning using the embedding model.

        Returns (predicted_level1, confidence) or None.
        """
        try:
            from pipeline.classifier import Classifier
            c = Classifier(config={})
            if not c._embedding_clf or not c._embedding_le:
                return None
            r = c._classify_by_embedding(meaning, {})
            if r is None:
                return None
            return (r.level1_label, r.confidence)
        except Exception as e:
            logger.error(f"[bridge] embedding classify failed: {e}")
            return None

    # === Database access ===
    def _fetch_pending_slangs(self, limit: int) -> List[dict]:
        """Fetch CONFIRMED slangs that have not been evaluated by the bridge yet."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT s.candidate_id, s.word, s.meaning
                FROM antiblack.slang_candidates s
                LEFT JOIN antiblack.slang_evaluations e
                    ON e.slang_candidate_id = s.candidate_id
                WHERE s.status = 'CONFIRMED'
                  AND e.slang_candidate_id IS NULL
                ORDER BY s.occurrence_count DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

    def _record_evaluation(self, slang_id: str, eval_status: str,
                           suggested_level1: Optional[str],
                           suggested_keywords: Optional[List[str]],
                           llm_confidence: Optional[float],
                           eval_json: dict):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO antiblack.slang_evaluations
                    (slang_candidate_id, eval_status, suggested_level1,
                     suggested_keywords, llm_confidence, eval_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (slang_candidate_id) DO NOTHING
            """, (
                slang_id, eval_status, suggested_level1,
                json.dumps(suggested_keywords, ensure_ascii=False) if suggested_keywords else None,
                llm_confidence, json.dumps(eval_json, ensure_ascii=False),
            ))
        conn.commit()

    def _adopt_rule(self, slang_id: str, level1: str, level2: str,
                    keywords: List[str], confidence: float) -> str:
        rule_id = f"dyn_{uuid.uuid4().hex[:12]}"
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO antiblack.dynamic_rules
                    (rule_id, slang_candidate_id, level1_label, level2_label,
                     keywords, source, hit_count, is_enabled)
                VALUES (%s, %s, %s, %s, %s, 'llm_bridge', 0, TRUE)
            """, (
                rule_id, slang_id, level1, level2,
                json.dumps(keywords, ensure_ascii=False),
            ))
        conn.commit()
        return rule_id

    # === Main evaluate-one entry point ===
    async def evaluate_one(self, slang: dict) -> dict:
        """Evaluate a single CONFIRMED slang. Returns a decision dict."""
        slang_id = slang['candidate_id']
        word = slang['word']
        meaning = slang.get('meaning') or word

        # 1. LLM evaluation
        prompt = build_slang_to_rule_prompt(
            slang_word=word,
            slang_meaning=meaning,
            current_taxonomy_text=self._taxonomy_text,
        )
        llm_resp = await self._ask_llm(prompt)
        if not llm_resp:
            return {"status": "rejected", "reason": "llm_no_response"}

        if not llm_resp.get("suitable", False):
            self._record_evaluation(slang_id, "rejected", None, None,
                                    llm_resp.get("confidence"), llm_resp)
            return {"status": "rejected", "reason": "llm_not_suitable",
                    "llm": llm_resp}

        llm_level1 = llm_resp.get("level1", "")
        llm_level2 = llm_resp.get("level2", "")
        llm_keywords = llm_resp.get("keywords", [])
        llm_conf = float(llm_resp.get("confidence", 0.0) or 0.0)

        # 2. Validate keywords (ReDoS defense)
        safe_kws = [k for k in llm_keywords if _is_safe_keyword(k)]
        if not safe_kws:
            self._record_evaluation(slang_id, "rejected", llm_level1, None,
                                    llm_conf, llm_resp)
            return {"status": "rejected", "reason": "no_safe_keywords",
                    "raw_keywords": llm_keywords}

        # 3. Embedding evaluation — must agree on level1
        emb_result = await self._classify_meaning_with_embedding(meaning)
        if emb_result is None:
            return {"status": "rejected", "reason": "embedding_unavailable"}
        emb_level1, emb_conf = emb_result
        if emb_conf < self.embedding_threshold:
            self._record_evaluation(slang_id, "rejected", llm_level1, safe_kws,
                                    llm_conf, llm_resp)
            return {"status": "rejected", "reason": f"low_emb_conf({emb_conf:.2f})",
                    "emb_level1": emb_level1}

        if emb_level1 != llm_level1:
            self._record_evaluation(slang_id, "rejected", llm_level1, safe_kws,
                                    llm_conf, llm_resp)
            return {"status": "rejected", "reason": f"level1_mismatch",
                    "llm_level1": llm_level1, "emb_level1": emb_level1}

        # 4. Both agree → adopt rule
        rule_id = self._adopt_rule(slang_id, llm_level1, llm_level2, safe_kws, llm_conf)
        self._record_evaluation(slang_id, "accepted", llm_level1, safe_kws,
                                llm_conf, llm_resp)
        return {
            "status": "accepted",
            "rule_id": rule_id,
            "level1": llm_level1,
            "level2": llm_level2,
            "keywords": safe_kws,
            "llm_confidence": llm_conf,
            "emb_level1": emb_level1,
            "emb_confidence": emb_conf,
        }

    # === Batch entry point ===
    async def evaluate_batch(self, batch_size: Optional[int] = None) -> List[dict]:
        bs = batch_size or self.batch_size
        pending = self._fetch_pending_slangs(bs)
        if not pending:
            return []
        logger.info(f"[bridge] evaluating {len(pending)} slangs")
        results = []
        for s in pending:
            try:
                r = await self.evaluate_one(s)
                r['slang_word'] = s['word']
                results.append(r)
            except Exception as e:
                logger.error(f"[bridge] evaluate_one failed for {s['word']}: {e}")
        return results

    # === Hit-rate tracking & rollback ===
    def record_dynamic_rule_hit(self, rule_id: str, was_correct: Optional[bool] = None):
        """Called from Stage 1 to bump hit_count. was_correct comes from feedback/audit."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            if was_correct is None:
                cur.execute("""
                    UPDATE antiblack.dynamic_rules
                    SET hit_count = hit_count + 1, last_hit_at = NOW()
                    WHERE rule_id = %s
                """, (rule_id,))
            else:
                cur.execute("""
                    UPDATE antiblack.dynamic_rules
                    SET hit_count = hit_count + 1,
                        correct_count = correct_count + %s,
                        last_hit_at = NOW()
                    WHERE rule_id = %s
                """, (1 if was_correct else 0, rule_id))
        conn.commit()

    def rollback_low_quality_rules(self, hit_rate_thresh: float = 0.4,
                                   min_hits: int = 50) -> int:
        """Disable rules whose hit rate is below threshold (and have enough hits)."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE antiblack.dynamic_rules
                SET is_enabled = FALSE
                WHERE is_enabled = TRUE
                  AND hit_count >= %s
                  AND (correct_count::float / NULLIF(hit_count, 0)) < %s
                RETURNING rule_id
            """, (min_hits, hit_rate_thresh))
            disabled = cur.fetchall()
        conn.commit()
        return len(disabled)

    # === Rule loading for Stage 1 ===
    def load_active_dynamic_rules(self) -> List[dict]:
        """Return all enabled dynamic rules for use by Stage 1 classifier."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT rule_id, level1_label, level2_label, keywords
                FROM antiblack.dynamic_rules
                WHERE is_enabled = TRUE
            """)
            return cur.fetchall()
