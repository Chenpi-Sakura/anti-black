"""
System APIs for AntiBlack system.
Handles system ready status and pipeline status.
"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, current_app

from utils import format_success_response, format_error_response

logger = logging.getLogger(__name__)
system_bp = Blueprint('system', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@system_bp.route('/system/ready', methods=['GET'])
def get_system_ready():
    """Get system ready status."""
    try:
        db = get_db()

        if db:
            status = db.get_system_ready_status()
        else:
            # Mock response for demo
            status = {
                "ready": True,
                "status": "READY",
                "health_checks": {
                    "database": "healthy",
                    "queue": "healthy",
                    "llm_api": "healthy",
                    "graph_engine": "healthy"
                },
                "bootstrap_progress": 100,
                "backfill_entity_count": 12680,
                "ready_threshold": 10000,
                "updated_at": datetime.utcnow().isoformat()
            }

        return jsonify(format_success_response(status))

    except Exception as e:
        logger.error(f"Error getting system ready status: {e}", exc_info=True)
        return jsonify(format_error_response(1211, "System ready status read failed")), 500


@system_bp.route('/system/pipeline-status', methods=['GET'])
def get_pipeline_status():
    """Get background patrol status."""
    try:
        db = get_db()

        if db:
            status = db.get_pipeline_status()
        else:
            # Mock response for demo
            status = {
                "patrol_enabled": True,
                "patrol_status": "RUNNING",
                "current_round_id": f"patrol_{datetime.utcnow().strftime('%Y%m%d_%H')}",
                "current_stage": "classifying",
                "last_patrol_at": datetime.utcnow().isoformat(),
                "next_patrol_at": None,
                "last_round_stats": {
                    "collected_messages": 240,
                    "generated_clues": 36,
                    "deep_analysis_count": 8
                }
            }

        return jsonify(format_success_response(status))

    except Exception as e:
        logger.error(f"Error getting pipeline status: {e}", exc_info=True)
        return jsonify(format_error_response(1212, "Pipeline status read failed")), 500