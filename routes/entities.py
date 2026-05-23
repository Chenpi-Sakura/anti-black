"""
Entity APIs for AntiBlack system.
Handles entity profile queries.
"""
import logging
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id

logger = logging.getLogger(__name__)
entities_bp = Blueprint('entities', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@entities_bp.route('/entities/<entity_id>/profile', methods=['GET'])
def get_entity_profile(entity_id: str):
    """Get entity profile with related entities."""
    try:
        include_relations = request.args.get('include_relations', 'true').lower() == 'true'
        relation_depth = min(int(request.args.get('relation_depth', 1)), 2)

        if relation_depth > 2:
            return jsonify(format_error_response(1503, "relation_depth exceeds limit")), 400

        db = get_db()
        profile = None

        if db:
            profile = db.get_entity_profile(entity_id, relation_depth)

        if not profile:
            # Generate mock profile for demo
            profile = _generate_mock_profile(entity_id)

        return jsonify(format_success_response(profile))

    except Exception as e:
        logger.error(f"Error getting entity profile: {e}", exc_info=True)
        return jsonify(format_error_response(1502, "Profile construction failed")), 500


def _generate_mock_profile(entity_id: str) -> dict:
    """Generate mock entity profile for demo."""
    return {
        "entity_id": entity_id,
        "entity_type": "WECHAT",
        "raw_value": "dyhao668",
        "first_seen": "2026-05-18T09:00:00+08:00",
        "last_seen": "2026-05-23T10:15:03+08:00",
        "occurrence_count": 9,
        "risk_distribution": [
            {"risk_label": "账号交易", "count": 6},
            {"risk_label": "黑产工具", "count": 3}
        ],
        "related_entities": [
            {
                "entity_id": generate_id("ent"),
                "entity_type": "URL",
                "raw_value": "https://t.me/demo",
                "relation_type": "使用",
                "confidence": 0.88
            }
        ],
        "recent_evidence": [
            {
                "clue_id": generate_id("clue"),
                "published_at": "2026-05-23T10:15:03+08:00",
                "snippet": "出抖号，千粉，换绑稳，加V:dyhao668"
            }
        ]
    }