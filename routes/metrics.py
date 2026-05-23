"""
Metrics APIs for AntiBlack system.
Handles monitoring metrics and overview.
"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, current_app

from utils import format_success_response, format_error_response

logger = logging.getLogger(__name__)
metrics_bp = Blueprint('metrics', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@metrics_bp.route('/metrics/overview', methods=['GET'])
def get_metrics_overview():
    """Get system metrics overview."""
    try:
        db = get_db()

        if db:
            metrics = db.get_latest_metrics()
            if metrics:
                response_data = metrics
            else:
                response_data = _generate_mock_metrics()
        else:
            # Mock response for demo
            response_data = _generate_mock_metrics()

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting metrics: {e}", exc_info=True)
        return jsonify(format_error_response(1901, "Metrics read failed")), 500


def _generate_mock_metrics() -> dict:
    """Generate mock metrics for demo."""
    return {
        "token_usage_today": 185230,
        "token_remaining_percent": 0.42,
        "collection_success_rate": 0.97,
        "total_entities": 12842,
        "total_relations": 3341,
        "messages_processed_today": 5320,
        "background_patrol_status": "RUNNING",
        "last_patrol_at": datetime.utcnow().isoformat(),
        "classification_distribution": [
            {
                "risk_label": "账号交易",
                "count": 120,
                "avg_confidence": 0.91,
                "trend": "up"
            },
            {
                "risk_label": "诈骗引流",
                "count": 85,
                "avg_confidence": 0.87,
                "trend": "flat"
            }
        ],
        "channel_status": [
            {
                "channel": "telegram",
                "status": "healthy",
                "latency_ms": 420
            },
            {
                "channel": "forum",
                "status": "healthy",
                "latency_ms": 610
            }
        ]
    }