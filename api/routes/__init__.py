"""
FastAPI routes package for AntiBlack API
"""
from fastapi import APIRouter
from api.routes import queries, clues, entities, feedback, system, taxonomy, metrics, evolution, export, channels, seed_words

router = APIRouter(prefix="/api/v1")

router.include_router(queries.router, tags=["查询"])
router.include_router(clues.router, tags=["线索"])
router.include_router(entities.router, tags=["实体"])
router.include_router(feedback.router, tags=["反馈"])
router.include_router(system.router, tags=["系统"])
router.include_router(taxonomy.router, tags=["分类体系"])
router.include_router(metrics.router, tags=["监控"])
router.include_router(evolution.router, tags=["自进化"])
router.include_router(export.router, tags=["导出"])
router.include_router(channels.router, tags=["渠道"])
router.include_router(seed_words.router, tags=["种子词"])