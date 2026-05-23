"""
Flask/FastAPI Server for AntiBlack System.
Provides REST API for all frontend interactions.
"""
import logging
import os
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import Flask, request, jsonify, g
from werkzeug.exceptions import HTTPException

from config import get_config
from utils import format_success_response, format_error_response, generate_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Create and configure Flask application."""
    app = Flask(__name__)

    # Load configuration
    config = get_config()
    app.config['DEBUG'] = config.app.debug
    app.config['JSON_AS_ASCII'] = False

    # Initialize services
    _init_services(app)

    # Register routes
    _register_routes(app)

    # Register error handlers
    _register_error_handlers(app)

    return app


def _init_services(app: Flask) -> None:
    """Initialize services on app startup."""
    from services.database import MongoDBService

    try:
        # Initialize MongoDB
        db_service = MongoDBService.get_instance()
        app.config['db'] = db_service
        logger.info("MongoDB service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB: {e}")
        # Continue anyway for demo mode with mock data


def _register_routes(app: Flask) -> None:
    """Register all API routes."""
    from routes.queries import queries_bp
    from routes.clues import clues_bp
    from routes.entities import entities_bp
    from routes.feedback import feedback_bp
    from routes.system import system_bp
    from routes.taxonomy import taxonomy_bp
    from routes.evolution import evolution_bp
    from routes.export import export_bp
    from routes.channels import channels_bp
    from routes.metrics import metrics_bp
    from routes.seed_words import seed_words_bp

    # Register blueprints with /api/v1 prefix
    app.register_blueprint(queries_bp, url_prefix='/api/v1')
    app.register_blueprint(clues_bp, url_prefix='/api/v1')
    app.register_blueprint(entities_bp, url_prefix='/api/v1')
    app.register_blueprint(feedback_bp, url_prefix='/api/v1')
    app.register_blueprint(system_bp, url_prefix='/api/v1')
    app.register_blueprint(taxonomy_bp, url_prefix='/api/v1')
    app.register_blueprint(evolution_bp, url_prefix='/api/v1')
    app.register_blueprint(export_bp, url_prefix='/api/v1')
    app.register_blueprint(channels_bp, url_prefix='/api/v1')
    app.register_blueprint(metrics_bp, url_prefix='/api/v1')
    app.register_blueprint(seed_words_bp, url_prefix='/api/v1')

    # Health check endpoint
    @app.route('/health')
    def health():
        return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})


def _register_error_handlers(app: Flask) -> None:
    """Register error handlers."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        return jsonify(format_error_response(
            code=e.code or 500,
            message=e.description,
            request_id=request.headers.get('X-Request-Id')
        )), e.code or 500

    @app.errorhandler(Exception)
    def handle_exception(e: Exception):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify(format_error_response(
            code=9999,
            message="Internal server error",
            request_id=request.headers.get('X-Request-Id')
        )), 500


def require_auth(f: Callable) -> Callable:
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            return jsonify(format_error_response(
                code=9001,
                message="Missing or invalid authorization header"
            )), 401

        token = auth_header[7:]

        # In demo mode, accept any token
        # In production, validate token against user database
        if not token:
            return jsonify(format_error_response(
                code=9001,
                message="Token is required"
            )), 401

        return f(*args, **kwargs)

    return decorated


def get_request_id() -> str:
    """Get request ID from header or generate new one."""
    return request.headers.get('X-Request-Id', generate_id("req"))


# ============ Main Entry Point ============

app = create_app()

if __name__ == '__main__':
    config = get_config()
    app.run(
        host=config.app.host,
        port=config.app.port,
        debug=config.app.debug
    )