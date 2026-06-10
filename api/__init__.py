"""
AntiBlack FastAPI Application Factory
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hook.

    Warms up the LightRAG singleton at startup so the first chat query
    doesn't pay the ~10-30s PG/Neo4j handshake cost.  If warmup fails
    (Neo4j/PG down, embedding model not pulled) we log and continue —
    the orchestrator's _kg_query will retry on first call, and other
    tools (search_clues, search_slang, ...) keep working.

    The 30s timeout prevents a hung Neo4j/PG handshake from blocking
    uvicorn startup indefinitely.
    """
    try:
        from services.lightrag_service import get_lightrag_integrator
        from config import get_config
        cfg = get_config()
        await asyncio.wait_for(
            get_lightrag_integrator(cfg._config),
            timeout=30.0,
        )
        logger.info("LightRAG warmed up at app startup")
    except asyncio.TimeoutError:
        logger.warning("LightRAG warmup timed out after 30s (will retry on first kg_query)")
    except Exception as e:
        logger.warning(f"LightRAG warmup failed (will retry on first kg_query): {e}")
    yield
    # No explicit close — the singleton has no async finalize.  PG pool
    # and Neo4j driver cleanup happens at process exit (uvicorn shutdown).


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="AntiBlack API",
        version="1.0.0",
        description="黑灰产情报分析Agent系统 API",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health")
    def health_check():
        return {"status": "healthy"}

    # Register routes
    from api.routes import router
    app.include_router(router)

    return app


# Create app instance for uvicorn
app = create_app()