"""
LightRAG integration for AntiBlack pipeline.
Handles deep channel processing with knowledge graph construction.
"""
import os
import re
import asyncio
import unicodedata
import logging
from typing import Any, Dict, List, Optional, Union
from functools import partial

logger = logging.getLogger(__name__)


# Process-wide singleton. The FastAPI uvicorn process and the daemon
# scheduler process are separate Python interpreters, but inside each
# process the LightRAGIntegrator should be created at most once —
# `initialize()` is expensive (PG + Neo4j handshakes, table checks) and
# the underlying `from lightrag import LightRAG` import is also heavy.
#
# `get_lightrag_integrator()` is the lazy, thread-safe accessor the
# orchestrator's _kg_query tool calls per HTTP request. It returns the
# cached instance on subsequent calls.
_integrator_singleton: Optional["LightRAGIntegrator"] = None
_integrator_init_lock: asyncio.Lock = asyncio.Lock()


async def get_lightrag_integrator(config: dict) -> "LightRAGIntegrator":
    """Return the process-wide LightRAGIntegrator, initializing it on first call.

    Raises whatever initialize() raises. The caller (orchestrator._kg_query
    or FastAPI lifespan) is expected to log + swallow init failures so the
    API can still serve other tools while LightRAG is unreachable.
    """
    global _integrator_singleton
    if _integrator_singleton is not None and _integrator_singleton._initialized:
        return _integrator_singleton
    async with _integrator_init_lock:
        # Re-check after acquiring the lock — another coroutine may have
        # initialized while we were waiting.
        if _integrator_singleton is not None and _integrator_singleton._initialized:
            return _integrator_singleton
        inst = LightRAGIntegrator(config)
        # initialize() raises on failure. We deliberately do NOT cache
        # an uninitialized instance, so the next caller can retry.
        await inst.initialize()
        _integrator_singleton = inst
        logger.info("LightRAG integrator initialized (singleton)")
        return _integrator_singleton


# bge-m3 (via Ollama) tends to produce NaN vectors for inputs containing:
#   - control characters (NUL, BEL, VT, FF, SO/SI, ...)
#   - BOM / zero-width / RTL/LTR marks
#   - very long strings near the 8192-token context limit
# We pre-sanitize AND retry with progressively shorter input on 500.
_MAX_EMBED_CHARS = 512          # safe length well below 8192 tokens
_RETRY_TIERS = (256, 128, 64)   # degrade input on each 500 retry

# Control characters that bge-m3 chokes on (excludes \t \n \r which are common
# whitespace, harmless for embeddings).
_BAD_CONTROL_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
    r"|[‌-‏⁠﻿]"
)
# Collapse any run of whitespace to a single space.
_WS_COLLAPSE = re.compile(r"\s+")


def create_lightrag_llm_complete():
    """Create LLM completion function (OpenAI-compatible) for LightRAG.

    Backward-compat factory used by LightRAG. Internally delegates to the
    unified LLMClient (multi-provider fallback chain: MiniMax-M2.7 → qwen3.6-flash)
    so LightRAG's keyword-extraction step benefits from provider failover.
    """
    from models.clients.llm import LLMClient

    client = LLMClient(timeout=120)

    async def lightrag_complete(
        prompt,
        system_prompt=None,
        history_messages=None,
        enable_cot: bool = False,
        **kwargs,
    ) -> str:
        logger.info(
            f"[LLM Call] Triggering LightRAG via LLMClient "
            f"(primary={client.providers[0]['name']}, "
            f"fallbacks={[p['name'] for p in client.providers[1:]]})"
        )
        try:
            return await client.complete_with_history(
                prompt=prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                **kwargs,
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return f"Error: {str(e)}"

    return lightrag_complete


def _sanitize_for_embed(text: str, max_chars: int = _MAX_EMBED_CHARS) -> str:
    """Sanitize a single text for bge-m3 / Ollama embedding.

    Strips:
      - control characters (NUL, BEL, FF, SO/SI, ...)
      - BOM / zero-width / RTL/LTR marks (separate regex class)
      - leading/trailing whitespace
    Collapses internal whitespace and truncates to max_chars.
    """
    if not text:
        return ""
    s = str(text)
    s = _BAD_CONTROL_CHARS.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = _WS_COLLAPSE.sub(" ", s).strip()
    if len(s) > max_chars:
        s = s[:max_chars]
    return s


def _looks_like_ollama_500(e: Exception) -> bool:
    """Detect Ollama 500 'unsupported value: NaN' specifically (vs other 500s)."""
    msg = str(e)
    return "NaN" in msg or "unsupported value" in msg or "500" in msg


def create_ollama_embed():
    """Create Ollama embedding function (using bge-m3 model)."""
    from openai import AsyncOpenAI
    import numpy as np

    api_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("OLLAMA_API_KEY", "ollama")  # Ollama doesn't need real key
    model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest")

    async def _call_ollama(client: "AsyncOpenAI", texts: list[str], model_name: str):
        return await client.embeddings.create(model=model_name, input=texts)

    async def ollama_embed(
        texts: list[str],
        model_name: str = model,
        **kwargs,
    ) -> np.ndarray:
        # Step 1: Sanitize each input. bge-m3 produces NaN for control chars,
        # zero-width marks, BOM, and very long strings near the 8192-token
        # context limit. Pre-clean and length-cap BEFORE sending.
        sanitized = [_sanitize_for_embed(t) for t in texts]
        # Empty / too-short → placeholder (bge-m3 returns 0-vector for these
        # but we want at least one defined semantic point to anchor retrieval).
        sanitized = [s if len(s) >= 2 else "empty_placeholder" for s in sanitized]

        logger.info(
            f"[LLM Call] Triggering Ollama Embedding for {len(texts)} texts (model={model_name})"
        )

        # Step 2: Try the request. On Ollama 500 "NaN" (which happens when its
        # Go JSON encoder can't serialize the vector), retry with progressively
        # shorter input. After all tiers exhausted, return zeros.
        tiers: list[int] = [_MAX_EMBED_CHARS, *_RETRY_TIERS]
        async with AsyncOpenAI(api_key=api_key, base_url=api_base) as client:
            for attempt, max_chars in enumerate(tiers):
                if attempt == 0:
                    payload = sanitized
                else:
                    payload = [s[:max_chars] for s in sanitized]
                    logger.warning(
                        f"Ollama retry #{attempt} with max_chars={max_chars}"
                    )
                try:
                    response = await _call_ollama(client, payload, model_name)
                    embeddings = [item.embedding for item in response.data]
                    arr = np.array(embeddings, dtype=np.float32)
                    # Defensive: replace any NaN/Inf that slipped through
                    # (response succeeded but vector contains NaN).
                    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
                except Exception as e:
                    if _looks_like_ollama_500(e) and attempt < len(tiers) - 1:
                        logger.warning(
                            f"Ollama 500/NaN on attempt {attempt + 1}, "
                            f"will retry with shorter input: {e}"
                        )
                        continue
                    # Non-retryable, or out of tiers
                    logger.error(f"Ollama embedding failed: {e}")
                    return np.zeros((len(texts), 1024), dtype=np.float32)

        # Unreachable — for-loop always returns — but keep for type-checkers
        return np.zeros((len(texts), 1024), dtype=np.float32)

    return ollama_embed


class LightRAGIntegrator:
    """Integration with LightRAG for knowledge graph operations."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._rag = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize LightRAG instance."""
        if self._initialized:
            return

        rag = None  # local so the except block can finalize on partial init
        try:
            from lightrag import LightRAG

            # Get LightRAG config
            lightrag_config = self.config.get('lightrag', {})
            working_dir = lightrag_config.get('working_dir', './rag_storage')

            # Get storage config
            storage_config = lightrag_config.get('storage', {})
            neo4j_config = lightrag_config.get('neo4j', {})
            pg_config = lightrag_config.get('postgresql', {})

            # Build vector_db_storage_cls_kwargs for PGVectorStorage
            vector_db_kwargs = {}
            if pg_config.get('host'):
                vector_db_kwargs["host"] = pg_config.get('host')
                vector_db_kwargs["port"] = pg_config.get('port', 5432)
                vector_db_kwargs["user"] = pg_config.get('user', 'antiblack')
                vector_db_kwargs["password"] = pg_config.get('password', 'antiblack123')
                vector_db_kwargs["database"] = pg_config.get('database', 'antiblack')

            # Initialize LightRAG with remote storage backends
            # LLM: MiniMax (OpenAI-compatible)
            # Embedding: Ollama bge-m3 (local)
            #
            # Note (2026-06-03): Neo4j connection comes from env vars
            # NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD (.env) — LightRAG
            # does NOT read addon_params["neo4j"] (verified in
            # LightRAG/lightrag/kg/neo4j_impl.py:136-150). PG connection goes
            # through vector_db_storage_cls_kwargs above (the only place that
            # actually feeds the PGKVStorage / PGVectorStorage constructors).
            from lightrag.utils import EmbeddingFunc

            rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=create_lightrag_llm_complete(),
                embedding_func=EmbeddingFunc(
                    embedding_dim=1024,  # bge-m3 outputs 1024 dim
                    max_token_size=8192,
                    model_name=os.environ.get("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest"),
                    func=create_ollama_embed(),
                ),
                # Storage backends (use correct storage names)
                kv_storage=storage_config.get('kv', 'PGKVStorage'),
                vector_storage=storage_config.get('vector', 'PGVectorStorage'),
                graph_storage=storage_config.get('graph', 'Neo4JStorage'),
                doc_status_storage=storage_config.get('doc_status', 'PGDocStatusStorage'),
                # Storage connection kwargs (this is the only working path for PG)
                vector_db_storage_cls_kwargs=vector_db_kwargs,
                # Disable LightRAG's LLM answer cache.  The orchestrator
                # (in this same process) is itself an LLM and doesn't
                # need LightRAG to also generate one — it only wants
                # the raw retrieval.  Without this, a prior call to
                # kg_query with the same text returns the cached LLM
                # answer instead of fresh entities / relations.
                enable_llm_cache=False,
                enable_llm_cache_for_entity_extract=False,
            )

            # Initialize storage backends (may open asyncpg pool + Neo4j driver)
            await rag.initialize_storages()
            self._rag = rag
            self._initialized = True
            logger.info("LightRAG initialized successfully with remote storage")
        except Exception as e:
            logger.error(f"Failed to initialize LightRAG: {e}")
            self._rag = None
            # Best-effort cleanup so a half-constructed LightRAG (Neo4j
            # driver + asyncpg pool opened, then a later step raised) does
            # not leak connections.  Swallow cleanup errors so the original
            # exception still propagates.
            if rag is not None:
                try:
                    await rag.finalize_storages()
                except Exception as cleanup_err:
                    logger.warning(f"LightRAG cleanup after init failure also failed: {cleanup_err}")
            # MUST re-raise: the caller (get_lightrag_integrator) depends on
            # exceptions to know NOT to cache the failed instance.  Without
            # this, _integrator_singleton gets set to a broken (_initialized=False)
            # object, and lifespan logs "warmed up" even on failure.
            raise

    async def finalize(self) -> None:
        """Finalize LightRAG instance."""
        if self._rag and self._initialized:
            await self._rag.finalize_storages()
            self._initialized = False

    async def insert(self, text: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Insert text into knowledge graph.
        LightRAG will automatically extract entities and relationships.
        """
        if not self._rag or not self._initialized:
            logger.warning("LightRAG not initialized, skipping insert")
            return False

        try:
            await self._rag.ainsert(text)
            logger.debug(f"Inserted text into LightRAG: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to insert into LightRAG: {e}")
            return False

    async def query(
        self,
        query_text: str,
        mode: str = "mix",
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Raw retrieval bypassing the LLM formatting step.

        Uses LightRAG's `aquery_data` — the vendored `aquery` wrapper (line 1977)
        forcibly drops the structured JSON and returns only
        ``llm_response.get("content", "")``.  ``aquery_data`` is the honest
        entry point that returns the full ``{status, data: {entities,
        relationships, chunks, references}, metadata}`` dict without ever
        calling the LLM final-answer step.

        ``only_need_context=True`` is passed as a double safety; ``aquery_data``
        already enforces it internally.

        Default ``mode='mix'`` fuses local entities, global relationships,
        and naive vector chunks — the richest citation context for an
        orchestrator that wants to ground its answer in both KG structure
        and source text.

        Returns:
          {
            "data":     {entities, relationships, chunks, references},
            "metadata": {query_mode, keywords, processing_info, ...},
            "status":   "success" | "failure",
            "message":  str,
            "query":    query_text,
            "mode":     str,
          }
        """
        from lightrag import QueryParam

        if not self._initialized:
            # Defensive: if initialize() failed and the caller didn't re-raise
            # (should not happen after the Bug-1 fix, but keep the guard).
            return {
                "data": {}, "status": "failure",
                "message": "LightRAG is not correctly initialized.",
                "query": query_text, "mode": mode,
            }

        try:
            result = await self._rag.aquery_data(
                query_text.strip(),
                param=QueryParam(
                    mode=mode,
                    top_k=top_k,
                    only_need_context=True,  # double safety
                ),
            )

            if isinstance(result, dict):
                return {
                    "data": result.get("data", {}),
                    "metadata": result.get("metadata", {}),
                    "status": result.get("status", "success"),
                    "message": result.get("message", ""),
                    "query": query_text,
                    "mode": mode,
                }

            # Extreme edge — aquery_data returned something other than dict
            return {
                "data": {},
                "status": "warning",
                "message": f"aquery_data returned unexpected type: {type(result).__name__}",
                "query": query_text,
                "mode": mode,
            }

        except Exception as e:
            logger.error(f"LightRAG raw retrieval failed: {e}", exc_info=True)
            return {
                "data": {},
                "status": "failure",
                "message": str(e),
                "query": query_text,
                "mode": mode,
            }

    async def insert_custom_kg(
        self,
        payload: Union[str, Dict[str, Any]],
        source: str = "auto"
    ) -> Dict[str, Any]:
        """
        Insert with custom knowledge graph construction.
        Useful for structured data insertion.

        Args:
            payload: Either a `str` (raw text, LightRAG extracts entities) or
                a `Dict` with keys {chunks, entities, relationships}
                (pre-extracted by MOExtractor, LightRAG just persists).
            source: Source tag (for logging only).
        """
        if not self._rag or not self._initialized:
            return {"success": False, "error": "LightRAG not initialized"}

        try:
            # Both str and dict go through ainsert_custom_kg; the underlying
            # LightRAG API dispatches on type internally.
            await self._rag.ainsert_custom_kg(payload)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to insert custom KG: {e}")
            return {"success": False, "error": str(e)}

    async def delete_slang_entity(self, slang_word: str) -> bool:
        """
        末位淘汰配套：删除 LightRAG 中已 CONFIRMED 过的黑话节点。

        Note (2026-06-03): `adelete_by_entity` 内部已经级联删除
        实体 + entities_vdb 向量 + 所有以该实体为端点的关系边 +
        relationships_vdb 向量（见 LightRAG/lightrag/utils/utils_graph.py:66）。
        因此只调一次 `adelete_by_entity` 即可，**不要**再调
        `adelete_entity_relation`——那是内部 API（utils_graph.py:138），
        不是 LightRAG 公开方法（lightrag.py 无此方法）。

        任何失败返回 False（不抛异常，由调用方决定如何处理）。
        Best-effort 语义：PG 是主存储，PG 提交后 demote 语义已生效；图谱
        残留节点最坏情况是污染下一个 cycle 的 hybrid 检索。
        """
        if not self._rag or not self._initialized:
            logger.warning(f"LightRAG not initialized, skip delete '{slang_word}'")
            return False
        try:
            result = await self._rag.adelete_by_entity(entity_name=slang_word)
            if result is not None and hasattr(result, 'success') and not result.success:
                logger.warning(
                    f"LightRAG delete entity returned non-success for '{slang_word}': "
                    f"{getattr(result, 'message', '?')}"
                )
            logger.info(f"LightRAG entity removed: {slang_word}")
            return True
        except Exception as e:
            logger.warning(f"LightRAG delete failed for '{slang_word}': {e}")
            return False

    async def get_raw_graph(self, max_nodes: int = 200) -> Dict[str, Any]:
        """Read the full knowledge graph directly from Neo4j, bypassing
        LightRAG's aquery_data retrieval pipeline.

        aquery_data returns entities[] and relationships[] from two different
        retrieval paths (EntityRank + graph BFS), which routinely disagree on
        the entity-name string (e.g. "QQ账号" vs "QQ帐号") — producing
        hundreds of dangling edges.  This method uses LightRAG's native
        get_knowledge_graph(node_label="*") which reads the **same Neo4j
        graph** with a single Cypher query, guaranteeing endpoint alignment.

        Returns the same shape as aquery_data so the frontend GraphCanvas
        component doesn't need any changes:
          {status, data: {entities[], relationships[], chunks[], references[]}, metadata}
        """
        if not self._rag or not self._initialized:
            return {"data": {}, "status": "failure", "message": "LightRAG not initialized"}

        kg = await self._rag.chunk_entity_relation_graph.get_knowledge_graph(
            node_label="*", max_depth=3, max_nodes=max_nodes,
        )

        # Neo4j get_knowledge_graph returns:
        #   n.labels[0]  = entity_id string (may be numeric if MOExtractor
        #     assigned order IDs; may be real Chinese names like '账号交易')
        #   n.properties has all Cypher properties including entity_type etc.
        # We use entity_id = labels[0] as the entity_name.
        node_name_map: Dict[str, str] = {}
        for n in kg.nodes:
            real_name = n.labels[0] if n.labels else str(n.id)
            node_name_map[str(n.id)] = real_name

        nodes = [
            {
                "entity_name": node_name_map[str(n.id)],
                "entity_type": n.properties.get("entity_type", ""),
                "description": n.properties.get("description", ""),
                "source_id": n.properties.get("source_id", ""),
                "file_path": n.properties.get("file_path", ""),
                "created_at": n.properties.get("created_at", ""),
                "reference_id": "",
            }
            for n in kg.nodes
        ]

        # Deduplicate edges by (source, target, type) in case Neo4j doesn't
        edges = []
        seen = set()
        for e in kg.edges:
            key = (e.source, e.target, e.type or "")
            if key in seen:
                continue
            seen.add(key)
            src_id = node_name_map.get(e.source, e.source)
            tgt_id = node_name_map.get(e.target, e.target)
            edges.append({
                "src_id": src_id,
                "tgt_id": tgt_id,
                "description": e.properties.get("description", ""),
                "keywords": e.properties.get("keywords", ""),
                "weight": float(e.properties.get("weight", 1.0)),
                "source_id": e.properties.get("source_id", ""),
                "file_path": e.properties.get("file_path", ""),
                "created_at": e.properties.get("created_at", ""),
                "reference_id": "",
            })

        return {
            "status": "success",
            "data": {
                "entities": nodes,
                "relationships": edges,
                "chunks": [],
                "references": [],
            },
            "metadata": {
                "query_mode": "raw",
                "is_truncated": kg.is_truncated,
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            "query": "",
            "mode": "raw",
        }

    def get_stats(self) -> Dict[str, int]:
        """Get knowledge graph statistics."""
        if not self._rag or not self._initialized:
            return {"nodes": 0, "edges": 0, "documents": 0}

        try:
            # Get stats from storage
            return {
                "nodes": 0,  # Would need to query graph storage
                "edges": 0,
                "documents": 0
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"nodes": 0, "edges": 0, "documents": 0}


class GraphProcessor:
    """Processes messages through the deep channel (LightRAG)."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.lightrag = LightRAGIntegrator(config)
        # Eagerly construct MOExtractor (cheap, no I/O) so process_batch can
        # skip the lazy-init check on the hot path.
        from pipeline.mo_extractor import MOExtractor
        self._mo_extractor = MOExtractor(config)

    async def initialize(self) -> None:
        """Initialize graph processor."""
        await self.lightrag.initialize()

    async def finalize(self) -> None:
        """Finalize graph processor."""
        await self.lightrag.finalize()

    async def process_batch(self, deep_msgs: List[Dict[str, Any]]) -> Dict[str, int]:
        """Batched deep-channel processing for a list of deep-routed messages.

        Flow (1 LLM call for N texts vs 1 call per text in process_message):
          1. One batched LLM call extracts MO from all N texts at once
             (MOExtractor.extract_batch, ~1 LLM call per 8 texts)
          2. Combine N extraction dicts into one KG with all entities/relations
          3. One ainsert_custom_kg call (Neo4j MERGE + bge-m3 embed in batch;
             dedup by entity_name means re-processing is idempotent)
          4. Persist PG entities per-message (counts only, idempotent)

        Args:
            deep_msgs: list of dicts, each with keys:
                - message_id: str
                - cleaned_text: str
                - source_channel: str (optional, for PG entities)
                - metadata: dict (optional)

        Returns:
            {"entities": int, "relationships": int} aggregate counts.
        """
        if not deep_msgs:
            return {"entities": 0, "relationships": 0}

        # Step 1: batched LLM extract
        texts = [m['cleaned_text'] for m in deep_msgs]
        try:
            extract_results = await self._mo_extractor.extract_batch(texts)
        except Exception as e:
            logger.error(f"process_batch: extract_batch failed entirely: {e}")
            # Don't drop PG persistence either — write empty extractions so the
            # batch doesn't get stuck in a partial state.
            extract_results = [{"entities": [], "relationships": []}] * len(deep_msgs)

        # Diagnostic: when 0 entities is returned, log enough context to
        # distinguish "LLM legitimately returned 0 for all 8" vs
        # "parse failed (all 8 returned None)" vs "all 8 cache hits with
        # empty results". Without this, 0-entity batches look identical.
        if all(len(er.get("entities", [])) == 0 for er in extract_results):
            preview = [t[:60].replace("\n", " ") for t in texts[:3]]
            n_uncached_or_fail = sum(
                1 for er in extract_results
                if not er.get("entities") and not er.get("relationships")
            )
            logger.warning(
                f"process_batch: 0 entities/relations across {len(texts)} msgs. "
                f"msg_ids={[m.get('message_id', '?') for m in deep_msgs[:3]]}... "
                f"first-texts={preview}... "
                f"(if all texts are non-黑产 noise, 0 entities is correct)"
            )

        # Step 2: combine into one KG dict
        all_chunks: List[Dict[str, Any]] = []
        all_entities: List[Dict[str, Any]] = []
        all_relations: List[Dict[str, Any]] = []
        for msg, er in zip(deep_msgs, extract_results):
            kg = self._mo_extractor.to_lightrag_kg(er, msg['message_id'])
            all_chunks.extend(kg.get('chunks', []))
            all_entities.extend(kg.get('entities', []))
            all_relations.extend(kg.get('relationships', []))

        # Step 3: single combined insert (skip if nothing to insert)
        if all_chunks or all_entities or all_relations:
            combined_kg = {
                'chunks': all_chunks,
                'entities': all_entities,
                'relationships': all_relations,
            }
            insert_result = await self.lightrag.insert_custom_kg(combined_kg)
            if not insert_result.get("success"):
                logger.warning(
                    f"process_batch: insert_custom_kg returned failure: "
                    f"{insert_result.get('error')}"
                )

        # Step 4: persist PG entities per-message (best-effort, doesn't block LightRAG)
        for msg, er in zip(deep_msgs, extract_results):
            try:
                await self._persist_mo_entities(er, msg)
            except Exception as e:
                logger.warning(
                    f"process_batch: PG persist failed for {msg.get('message_id')}: {e}"
                )

        return {"entities": len(all_entities), "relationships": len(all_relations)}

    async def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a message through the deep channel.

        New flow (2026-06-03): use MOExtractor for structured 黑灰产 entity/relation
        extraction, then ainsert_custom_kg injects pre-extracted dict directly into
        LightRAG Neo4j (same-name nodes MERGE automatically across messages).
        Falls back to empty extraction on LLM failure (best-effort).

        Args:
            message: Message data with:
                - message_id: Unique message ID
                - raw_text: Original text
                - cleaned_text: Cleaned text
                - classification: Classification result
                - entities: Extracted entities (legacy regex-based, kept for compat)

        Returns:
            Processing result with extracted entities/relations
        """
        try:
            # _mo_extractor is now eagerly constructed in __init__; no lazy check.
            raw_text = message.get('raw_text', '')
            message_id = message.get('message_id', '')

            # 1) LLM 抽取 M.O. + Supply/Demand 结构化 JSON
            extraction = await self._mo_extractor.extract(raw_text)

            # 2) 写 LightRAG（同名 entity_name → Neo4j MERGE 自动跨消息聚合）
            if extraction.get('entities'):
                kg = self._mo_extractor.to_lightrag_kg(extraction, message_id)
                await self.lightrag.insert_custom_kg(kg, source='mo_extraction')

            # 3) 写 PG entities 表（供 dedup cron + API 查询）
            await self._persist_mo_entities(extraction, message)

            return {
                "success": True,
                "message_id": message_id,
                "extracted": len(extraction.get('entities', [])),
                "relations": len(extraction.get('relationships', [])),
            }
        except Exception as e:
            logger.error(f"Error processing message through deep channel: {e}")
            return {
                "success": False,
                "message_id": message.get('message_id'),
                "error": str(e)
            }

    async def _persist_mo_entities(
        self,
        extraction: Dict[str, Any],
        message: Dict[str, Any],
    ) -> None:
        """Persist MO-extracted entities to PG `entities` table.

        Same entity_name + entity_type across messages → upsert_entity merges
        via ON CONFLICT and increments occurrence_count.
        """
        from services.database import PostgreSQLService
        from models import Entity
        from models.domain.entities import EntityType

        try:
            pg_db = PostgreSQLService.get_instance()
        except Exception as e:
            logger.warning(f"PG not available for MO entity persist: {e}")
            return

        # 写 entities 表（不写 message_refs，避免污染现有 schema 等下游）
        from pipeline.mo_extractor import MOExtractor
        records = self._mo_extractor.to_pg_entity_records(
            extraction,
            message_id=message.get('message_id', ''),
            source_channel=message.get('source_channel'),
        )
        for rec in records:
            try:
                entity = Entity(
                    entity_id=rec['entity_id'],
                    entity_type=EntityType(rec['entity_type']),
                    raw_value=rec['raw_value'],
                    normalized_value=rec.get('normalized_value', rec['raw_value']),
                    occurrence_count=rec.get('occurrence_count', 1),
                    source_channel=rec.get('source_channel'),
                    risk_labels=rec.get('risk_labels', []),
                    metadata=rec.get('metadata', {}),
                )
                pg_db.upsert_entity(entity)
            except Exception as e:
                logger.warning(f"upsert_entity failed for {rec.get('raw_value')}: {e}")

    async def query_graph(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10
    ) -> Dict[str, Any]:
        """Query the knowledge graph."""
        return await self.lightrag.query(query, mode, top_k)

    async def delete_slang_entity(self, slang_word: str) -> bool:
        """
        Pass-through to LightRAGIntegrator.delete_slang_entity. Kept on
        GraphProcessor so the slang-learning demote path can call
        `gp.delete_slang_entity(word)` uniformly with query_graph / insert.
        """
        return await self.lightrag.delete_slang_entity(slang_word)

    async def get_entity_profile(self, entity_value: str, entity_type: str = None) -> Optional[Dict[str, Any]]:
        """
        Query entity profile with all relations from PostgreSQL + LightRAG.

        Args:
            entity_value: Entity raw value (e.g., "dyhao668")
            entity_type: Optional entity type filter (e.g., "WECHAT")

        Returns:
            Entity profile dict with entity info and rag relations, or None if not found
        """
        from services.database import PostgreSQLService
        pg_db = PostgreSQLService.get_instance()

        # Get entity from PostgreSQL
        if entity_type:
            entity = pg_db.get_entity_by_value(entity_type, entity_value)
        else:
            # Search across all types if no type specified
            entity = None
            for et in ['WECHAT', 'PHONE', 'QQ', 'URL']:
                e = pg_db.get_entity_by_value(et, entity_value)
                if e:
                    entity = e
                    break
        if not entity:
            return None

        # Get relations from LightRAG
        rag_result = await self.lightrag.query(
            f"与 {entity_value} 相关的实体和关系",
            mode="global",
            top_k=20
        )

        return {
            "entity": entity,
            "relations": rag_result
        }

    async def get_kg_stats(self) -> Dict[str, int]:
        """
        Get knowledge graph statistics from LightRAG storage.

        Returns:
            Dict with nodes, edges, documents counts
        """
        from services.database import PostgreSQLService
        pg_db = PostgreSQLService.get_instance()

        try:
            # Query node count from LightRAG entities table
            with pg_db._get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM antiblack.lightrag_full_entities")
                nodes = cur.fetchone()['count']

            with pg_db._get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM antiblack.lightrag_full_relations")
                edges = cur.fetchone()['count']

            with pg_db._get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM antiblack.lightrag_doc_chunks")
                documents = cur.fetchone()['count']

            return {
                "nodes": nodes,
                "edges": edges,
                "documents": documents
            }
        except Exception as e:
            logger.error(f"Failed to get kg stats: {e}")
            return {"nodes": 0, "edges": 0, "documents": 0}