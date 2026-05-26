"""
AntiBlack FastAPI Application Factory
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="AntiBlack API",
        version="1.0.0",
        description="黑灰产情报分析Agent系统 API",
        docs_url="/docs",
        redoc_url="/redoc"
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