"""
Knowledge Graph query endpoints — direct wrappers around LightRAG integrator.

  GET /kg/query                               full KG retrieval
  GET /kg/entities/{entity_name}/subgraph     entity-centric local subgraph

Both endpoints return LightRAG.aquery_data's native shape (LightRAG/lightrag/lightrag.py:2000-2098)
so the frontend can stay shape-stable:

  {
    "status": "success",
    "data": {
      "entities":      [ {entity_name, entity_type, description, ...} ],
      "relationships": [ {src_id, tgt_id, description, keywords, weight, ...} ],
      "chunks":        [ {content, file_path, chunk_id, reference_id} ],
      "references":    [ {reference_id, file_path} ]
    },
    "metadata": { ... }
  }
"""
import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from services.lightrag_service import get_lightrag_integrator
from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kg", tags=["知识图谱"])

QUERY_TIMEOUT_S = 60.0
# Semaphore to cap concurrent LightRAG queries — protects the provider from
# RPM/TPM blow-ups when multiple analysts query the KG page simultaneously.
_MAX_CONCURRENT_KG = 3
_kg_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_KG)


async def _call_lightrag(text: str, mode: str, top_k: int) -> Dict[str, Any]:
    """Get or init the singleton LightRAG integrator, then query with
    semaphore + timeout.  Raises HTTPException on failure."""
    try:
        integrator = await get_lightrag_integrator(get_config()._config)
    except Exception as e:
        logger.error("LightRAG init failed: %s", e, exc_info=True)
        raise HTTPException(503, f"LightRAG 未就绪: {e}")

    if _kg_semaphore.locked():
        raise HTTPException(
            429,
            f"并发查询过多, 超过 {_MAX_CONCURRENT_KG} 个上限, 请稍后重试",
        )

    async with _kg_semaphore:
        try:
            if mode == "raw":
                # Direct Neo4j read via LightRAG's internal graph storage.
                # The aquery_data path returns entities[] and relationships[]
                # from two different retrieval paths which routinely produce
                # dangling edges (endpoints that don't match any entity).
                # get_raw_graph reads the **same Neo4j graph** with one
                # Cypher query, guaranteeing 100% endpoint alignment.
                result = await integrator.get_raw_graph(max_nodes=top_k)
            else:
                result = await asyncio.wait_for(
                    integrator.query(text, mode=mode, top_k=top_k),
                    timeout=QUERY_TIMEOUT_S,
                )
        except asyncio.TimeoutError:
            raise HTTPException(504, "查询超时, 请缩短文本或减少 top_k")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("kg_query failed: %s", e, exc_info=True)
            raise HTTPException(500, f"查询失败: {type(e).__name__}")

    return result


@router.get("/query", summary="知识图谱查询")
async def kg_query(
    text: str = Query("", min_length=0, max_length=500, description="查询文本 (raw 模式不需要)"),
    mode: str = Query("raw", pattern="^(mix|hybrid|local|global|naive|raw)$"),
    top_k: int = Query(200, ge=1, le=2000),
) -> Dict[str, Any]:
    """Run a LightRAG query and return the full structured result.

    Parameters match the kg_query Agent tool's API so the backend is shape-
    consistent with the existing orchestrator path.
    """
    return await _call_lightrag(text, mode, top_k)


@router.get("/entities/{entity_name}/subgraph", summary="实体的局部子图")
async def kg_entity_subgraph(
    entity_name: str,
    depth: int = Query(1, ge=1, le=2, description="BFS 深度, 1 或 2"),
    top_k: int = Query(10, ge=1, le=200),
) -> Dict[str, Any]:
    """Entity-centric local subgraph.

    Runs a LightRAG query with mode='local' using the entity name as seed,
    then server-side BFS-prunes the result to *depth* hops so the frontend
    never receives disconnected noise.
    """
    query_text = f"实体 {entity_name} 的关联实体和关系"
    try:
        result = await _call_lightrag(query_text, "local", top_k)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("kg_subgraph failed: %s", e, exc_info=True)
        raise HTTPException(500, f"子图查询失败: {e}")

    data = result.get("data", {}) or {}
    rels = data.get("relationships", []) or []
    ents = data.get("entities", []) or []

    # Collect the connected-entity set so we can discard isolated nodes
    connected: set = set()
    adj: Dict[str, set] = {entity_name: set()}
    for r in rels:
        s, t = r.get("src_id"), r.get("tgt_id")
        if s and t:
            connected.add(s)
            connected.add(t)
            adj.setdefault(s, set()).add(t)
            adj.setdefault(t, set()).add(s)

    # BFS from the seed entity
    keep: set = {entity_name} | connected
    frontier = {entity_name}
    for _ in range(depth):
        nxt: set = set()
        for n in frontier:
            nxt |= adj.get(n, set())
        keep |= nxt
        frontier = nxt
        if not frontier:
            break

    data["entities"] = [e for e in ents if e.get("entity_name") in keep]
    data["relationships"] = [
        r for r in rels
        if r.get("src_id") in keep and r.get("tgt_id") in keep
    ]
    result["data"] = data
    result["metadata"] = {
        **(result.get("metadata") or {}),
        "seed_entity": entity_name,
        "depth": depth,
    }
    return result
