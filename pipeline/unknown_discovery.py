"""Unknown category discovery (Phase 2.3).

Daily job that:
  1. Pulls recent '未知/其他' samples from clues
  2. Embeds them via Ollama bge-m3 (1024D)
  3. Reduces to 10D with UMAP
  4. Clusters with HDBSCAN
  5. Centroid-samples top 30 per cluster
  6. Asks LLM to name the cluster (strictly-constrained prompt)
  7. Validates via 3 code-level assertions (dedup, length, confidence)
  8. Dedups against existing candidate pool
  9. Writes to antiblack.pending_category_proposals for human review

All optional ML deps (umap-learn, hdbscan) are imported lazily — if missing
the module can still be imported and the prompt-only path still works.
"""
import asyncio
import json
import logging
import os
import pickle
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import psycopg2
import psycopg2.extras

from config import get_config
from pipeline.prompts import (
    SYSTEM_ROLE_RISK_ANALYST,
    build_cluster_naming_prompt,
    format_taxonomy_text,
)

logger = logging.getLogger(__name__)


class _OptionalDeps:
    umap = None
    hdbscan = None

    @classmethod
    def try_import(cls):
        if cls.umap is None:
            try:
                import umap  # type: ignore
                cls.umap = umap
            except ImportError:
                pass
        if cls.hdbscan is None:
            try:
                import hdbscan  # type: ignore
                cls.hdbscan = hdbscan
            except ImportError:
                pass


def _extract_json(raw: str) -> Optional[dict]:
    """Robustly extract a JSON object from an LLM response."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return None


def _format_taxonomy_for_prompt(cfg) -> str:
    cats = cfg.get('taxonomy', {}).get('categories', [])
    return format_taxonomy_text(cats)


class UnknownDiscovery:
    """End-to-end unknown category discovery pipeline."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        cfg = get_config()
        self.db_cfg = cfg.postgresql
        self.ud_cfg = self.config.get('unknown_discovery', {})
        self._taxonomy_text = _format_taxonomy_for_prompt(cfg._config)

        # UMAP params
        self.umap_n_components = int(self.ud_cfg.get('umap_n_components', 10))
        self.umap_n_neighbors = int(self.ud_cfg.get('umap_n_neighbors', 15))
        self.umap_min_dist = float(self.ud_cfg.get('umap_min_dist', 0.0))
        self.umap_metric = self.ud_cfg.get('umap_metric', 'cosine')
        self.umap_random_state = int(self.ud_cfg.get('umap_random_state', 42))

        # HDBSCAN params
        self.hdbscan_min_cluster_size = int(self.ud_cfg.get('min_cluster_size', 30))
        self.hdbscan_min_samples = int(self.ud_cfg.get('min_samples', 5))
        self.hdbscan_metric = self.ud_cfg.get('hdbscan_metric', 'euclidean')

        # Admission gate
        self.min_cluster_size_for_proposal = int(self.ud_cfg.get('min_cluster_size_for_proposal', 50))
        self.min_appearance_days = int(self.ud_cfg.get('min_appearance_days', 3))
        self.top_k = int(self.ud_cfg.get('top_k_samples_per_cluster', 30))

        # Code-level assertions
        self.cosine_dedup_threshold = float(self.ud_cfg.get('cosine_dedup_threshold', 0.85))
        self.min_level2_chars = int(self.ud_cfg.get('min_level2_chars', 2))
        self.max_level2_chars = int(self.ud_cfg.get('max_level2_chars', 6))
        self.min_llm_confidence = float(self.ud_cfg.get('min_llm_confidence', 0.8))

        # Cache
        self._umap_model_path = './models/ml/assets/umap_unknown_discovery.pkl'

    def _get_conn(self):
        return psycopg2.connect(
            host=self.db_cfg.host, port=self.db_cfg.port,
            user=self.db_cfg.user, password=self.db_cfg.password,
            database=self.db_cfg.database,
        )

    def fetch_unknown_samples(self, lookback_days: int = 7) -> List[dict]:
        """Fetch recent '未知/其他' samples, deduplicated by cleaned_text."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH samples AS (
                    SELECT c.clue_id, c.cleaned_text, c.created_at,
                           ROW_NUMBER() OVER (PARTITION BY c.cleaned_text ORDER BY c.created_at) AS rn
                    FROM antiblack.clues c
                    WHERE c.risk_label_level1 = '未知/其他'
                      AND c.created_at > NOW() - (%s || ' days')::INTERVAL
                      AND LENGTH(c.cleaned_text) BETWEEN 8 AND 500
                )
                SELECT clue_id, cleaned_text, created_at
                FROM samples WHERE rn = 1
                ORDER BY created_at DESC
            """, (str(lookback_days),))
            rows = cur.fetchall()
        conn.close()
        return rows

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Call Ollama bge-m3 to get 1024-dim embeddings."""
        import httpx
        all_embs = []
        with httpx.Client(timeout=60.0) as client:
            for i in range(0, len(texts), 32):
                batch = texts[i:i + 32]
                r = client.post(
                    "http://localhost:11434/api/embed",
                    json={"model": "bge-m3", "input": batch},
                )
                r.raise_for_status()
                all_embs.extend(r.json().get('embeddings', []))
        return np.array(all_embs, dtype=np.float32)

    def reduce_umap(self, X: np.ndarray, fit: bool = True):
        """UMAP reduce to n_components dimensions. Persists model for incremental transform."""
        _OptionalDeps.try_import()
        if _OptionalDeps.umap is None:
            raise ImportError("umap-learn is not installed; pip install umap-learn")

        if fit or not os.path.exists(self._umap_model_path):
            logger.info(f"[discovery] fit_transform UMAP n_neighbors={self.umap_n_neighbors} n_components={self.umap_n_components}")
            umap_model = _OptionalDeps.umap.UMAP(
                n_neighbors=self.umap_n_neighbors,
                n_components=self.umap_n_components,
                min_dist=self.umap_min_dist,
                metric=self.umap_metric,
                random_state=self.umap_random_state,
            )
            X_low = umap_model.fit_transform(X)
            os.makedirs(os.path.dirname(self._umap_model_path), exist_ok=True)
            with open(self._umap_model_path, 'wb') as f:
                pickle.dump(umap_model, f)
            return X_low, umap_model
        else:
            with open(self._umap_model_path, 'rb') as f:
                umap_model = pickle.load(f)
            logger.info("[discovery] transform with persisted UMAP model")
            return umap_model.transform(X), umap_model

    def cluster_hdbscan(self, X_low: np.ndarray):
        """Cluster with HDBSCAN. Returns (cluster_labels, clusterer)."""
        _OptionalDeps.try_import()
        if _OptionalDeps.hdbscan is None:
            raise ImportError("hdbscan is not installed; pip install hdbscan")

        clusterer = _OptionalDeps.hdbscan.HDBSCAN(
            min_cluster_size=self.hdbscan_min_cluster_size,
            min_samples=self.hdbscan_min_samples,
            metric=self.hdbscan_metric,
        )
        cluster_labels = clusterer.fit_predict(X_low)
        return cluster_labels, clusterer

    def centroid_sample(self, X_low: np.ndarray, cluster_idx: np.ndarray,
                        texts: List[str], top_k: int) -> List[str]:
        """Return top_k texts closest to the cluster centroid."""
        if len(cluster_idx) == 0:
            return []
        centroid = X_low[cluster_idx].mean(axis=0)
        dists = np.linalg.norm(X_low[cluster_idx] - centroid, axis=1)
        order = np.argsort(dists)[:top_k]
        return [texts[cluster_idx[i]] for i in order]

    async def name_cluster_with_llm(self, sample_texts: List[str],
                                     cluster_size: int) -> Optional[dict]:
        prompt = build_cluster_naming_prompt(
            cluster_samples_text="\n".join(f"  {i+1}. {t}" for i, t in enumerate(sample_texts)),
            current_taxonomy_text=self._taxonomy_text,
            cluster_size=cluster_size,
        )
        try:
            from models.clients.llm import LLMClient
            client = LLMClient(timeout=120)
            raw = await client.complete(
                prompt=prompt,
                system_prompt=SYSTEM_ROLE_RISK_ANALYST,
                max_tokens=512,
                extra_body={"reasoning_effort": "low"},
            )
            return _extract_json(raw)
        except Exception as e:
            logger.error(f"[discovery] LLM cluster naming failed: {e}")
            return None

    def cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def is_duplicate_of_existing(self, level1: str, level2: str) -> Tuple[bool, Optional[str]]:
        """Check whether (level1, level2) is semantically a duplicate of any
        existing level1/level2 category. Returns (is_dup, similar_category)."""
        # Load existing taxonomy
        cfg = get_config()
        cats = cfg.get('taxonomy', {}).get('categories', [])

        # Encode proposed level2 with embedding model
        try:
            from pipeline.classifier import Classifier
            c = Classifier(config={})
            emb_clf = c._embedding_clf
            if emb_clf is None:
                return False, None
            # Encode the level2 text via Ollama
            import httpx
            with httpx.Client(timeout=30.0) as client:
                r = client.post(
                    "http://localhost:11434/api/embed",
                    json={"model": "bge-m3", "input": [level2]},
                )
                r.raise_for_status()
                proposal_emb = np.array(r.json()['embeddings'][0], dtype=np.float32)
        except Exception as e:
            logger.warning(f"[discovery] dedup embed failed: {e}")
            return False, None

        # Compare with all level1 names
        for cat in cats:
            l1 = cat.get('level1_name', '')
            sim = self.cosine(proposal_emb, self._embed_single_text_cached(l1))
            if sim > self.cosine_dedup_threshold:
                return True, l1
        return False, None

    _emb_cache: Dict[str, np.ndarray] = {}

    def _embed_single_text_cached(self, text: str) -> np.ndarray:
        """Embed a single text (cached)."""
        if text in self._emb_cache:
            return self._emb_cache[text]
        try:
            import httpx
            with httpx.Client(timeout=30.0) as client:
                r = client.post(
                    "http://localhost:11434/api/embed",
                    json={"model": "bge-m3", "input": [text]},
                )
                r.raise_for_status()
                emb = np.array(r.json()['embeddings'][0], dtype=np.float32)
        except Exception:
            emb = np.zeros(1024, dtype=np.float32)
        self._emb_cache[text] = emb
        return emb

    def code_level_assertions(self, llm_resp: dict) -> Tuple[bool, str]:
        """Run 3 code-level assertions on the LLM's response. Returns (pass, reason)."""
        # 1. length
        level2 = llm_resp.get("proposed_level2", "")
        if len(level2) < self.min_level2_chars or len(level2) > self.max_level2_chars:
            return False, f"length {len(level2)} not in [{self.min_level2_chars},{self.max_level2_chars}]"
        # 2. confidence
        conf = float(llm_resp.get("confidence", 0.0) or 0.0)
        if conf < self.min_llm_confidence:
            return False, f"confidence {conf:.2f} < {self.min_llm_confidence}"
        # 3. is_new_category true (otherwise nothing to add)
        if not llm_resp.get("is_new_category", False):
            return False, "is_new_category=false"
        return True, "ok"

    def write_proposal(self, cluster_id: str, cluster_size: int,
                       sample_texts: List[str], cluster_mean_emb: np.ndarray,
                       llm_resp: dict):
        """Write a new pending proposal. Returns proposal_id or None on failure."""
        proposal_id = f"prop_{uuid.uuid4().hex[:16]}"
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO antiblack.pending_category_proposals
                        (proposal_id, cluster_id, proposed_level1, proposed_level2,
                         chain_of_thought, llm_confidence, sample_texts,
                         sample_size, embedding, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """, (
                    proposal_id, cluster_id,
                    llm_resp.get("proposed_level1", "未知/其他"),
                    llm_resp.get("proposed_level2", ""),
                    llm_resp.get("chain_of_thought", ""),
                    float(llm_resp.get("confidence", 0.0)),
                    json.dumps(sample_texts, ensure_ascii=False),
                    cluster_size,
                    cluster_mean_emb.tolist(),
                ))
            conn.commit()
            return proposal_id
        except Exception as e:
            conn.rollback()
            logger.error(f"[discovery] write_proposal failed: {e}")
            return None
        finally:
            conn.close()

    def find_duplicate_in_pool(self, level2: str) -> Optional[dict]:
        """Look up the candidate pool for any pending proposal that's semantically
        close to the proposed level2."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT proposal_id, proposed_level2, embedding
                    FROM antiblack.pending_category_proposals
                    WHERE status = 'pending' AND embedding IS NOT NULL
                """)
                candidates = cur.fetchall()
        finally:
            conn.close()
        if not candidates:
            return None
        proposal_emb = self._embed_single_text_cached(level2)
        best, best_sim = None, 0.0
        for c in candidates:
            if not c['embedding']:
                continue
            emb = np.array(c['embedding'], dtype=np.float32)
            sim = self.cosine(proposal_emb, emb)
            if sim > best_sim:
                best, best_sim = c, sim
        if best_sim > self.cosine_dedup_threshold:
            return best
        return None

    async def run(self, lookback_days: int = 7) -> List[dict]:
        """Run end-to-end discovery. Returns a list of accepted proposals.

        P3-1 (2026-06-07): batched processing. Previously ran 5-10k samples
        in one go (UMAP+HDBSCAN took 20-40 min, blocking the daemon).
        Now chunks at `batch_size` (default 5000) with asyncio.sleep(0)
        between batches to yield to the event loop.

        P3-2 (2026-06-07): UMAP recalibration. First batch uses
        fit_transform; subsequent batches within the same run use
        transform only. The `umap_unknown_discovery.pkl` model
        persists to disk, so across runs the topology is stable.
        Daily / per-N-batches full recalibration is handled by
        daemon_scheduler (separate concern).
        """
        samples = self.fetch_unknown_samples(lookback_days=lookback_days)
        logger.info(f"[discovery] fetched {len(samples)} unknown samples")
        if len(samples) < self.hdbscan_min_cluster_size:
            logger.info("[discovery] not enough samples to cluster")
            return []

        batch_size = int(self.ud_cfg.get('run_batch_size', 5000))
        accepted: List[dict] = []
        umap_model = None

        # P3-2: First batch fits UMAP, rest use transform.
        # P3-1: Process in chunks so a 50k-sample run doesn't
        # hold the event loop for 20+ minutes.
        for batch_start in range(0, len(samples), batch_size):
            batch_end = min(batch_start + batch_size, len(samples))
            batch_samples = samples[batch_start:batch_end]
            logger.info(
                f"[discovery] processing batch {batch_start}-{batch_end} "
                f"({len(batch_samples)} samples) of {len(samples)} total"
            )
            batch_accepted, umap_model = await self._process_one_batch(
                batch_samples, fit_umap=(batch_start == 0), umap_model=umap_model
            )
            accepted.extend(batch_accepted)
            # Yield to event loop so other loops (Kafka consumer, slang
            # evolution, etc.) get a turn. Keeps the daemon responsive
            # during the multi-minute discovery run.
            await asyncio.sleep(0)
        return accepted

    async def _process_one_batch(
        self, samples: List[dict], fit_umap: bool, umap_model
    ) -> tuple:
        """Run a single batch through embed → UMAP → HDBSCAN → LLM naming.

        Returns (accepted_proposals, umap_model_for_next_batch).
        """
        texts = [s['cleaned_text'] for s in samples]
        X = await asyncio.to_thread(self.embed_texts, texts)
        X_low, umap_model = await asyncio.to_thread(
            self.reduce_umap, X, fit_umap
        )
        cluster_labels, _ = await asyncio.to_thread(
            self.cluster_hdbscan, X_low
        )

        # Build list of cluster descriptors to process
        unique_labels = set(cluster_labels.tolist()) - {-1}
        cluster_descs = []
        for cid in unique_labels:
            cluster_idx = np.where(cluster_labels == cid)[0]
            if len(cluster_idx) < self.min_cluster_size_for_proposal:
                continue
            sample_texts = self.centroid_sample(X_low, cluster_idx, texts, self.top_k)
            cluster_mean = X[cluster_idx].mean(axis=0)
            cluster_descs.append((cid, cluster_idx, sample_texts, cluster_mean))

        # LLM naming + assertions + dedup + write — gather with
        # P0-3 LLMClient._semaphore (global cap 4 concurrent).
        # One gather() over all clusters so they all run in parallel
        # within the semaphore limit.
        async def _process_one_cluster(cid, cluster_idx, sample_texts, cluster_mean):
            llm_resp = await self.name_cluster_with_llm(sample_texts, len(cluster_idx))
            if llm_resp is None:
                return None
            ok, reason = self.code_level_assertions(llm_resp)
            if not ok:
                logger.info(f"[discovery] cluster {cid} rejected: {reason}")
                return None
            is_dup, similar = await asyncio.to_thread(
                self.is_duplicate_of_existing,
                llm_resp.get("proposed_level1", ""),
                llm_resp.get("proposed_level2", ""),
            )
            if is_dup:
                logger.info(f"[discovery] cluster {cid} dedup-merged into {similar!r}")
                return None
            pool_dup = await asyncio.to_thread(
                self.find_duplicate_in_pool, llm_resp.get("proposed_level2", "")
            )
            if pool_dup:
                logger.info(f"[discovery] cluster {cid} merged into pool proposal {pool_dup['proposal_id']}")
                return None
            proposal_id = await asyncio.to_thread(
                self.write_proposal,
                cluster_id=str(cid),
                cluster_size=len(cluster_idx),
                sample_texts=sample_texts,
                cluster_mean_emb=cluster_mean,
                llm_resp=llm_resp,
            )
            return {
                "proposal_id": proposal_id,
                "cluster_id": str(cid),
                "size": len(cluster_idx),
                "level1": llm_resp.get("proposed_level1"),
                "level2": llm_resp.get("proposed_level2"),
                "confidence": llm_resp.get("confidence"),
            }

        results = await asyncio.gather(
            *(_process_one_cluster(*d) for d in cluster_descs),
            return_exceptions=True,
        )
        accepted = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"[discovery] cluster processing failed: {r}")
                continue
            if r is not None:
                accepted.append(r)
        return accepted, umap_model
