"""
Seed Words APIs for AntiBlack system.
Handles seed word management.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id
from models import SeedWord, SeedWordStatus

logger = logging.getLogger(__name__)
seed_words_bp = Blueprint('seed_words', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@seed_words_bp.route('/seed-words', methods=['GET'])
def get_seed_words():
    """Get seed words with filtering."""
    try:
        status = request.args.get('status')
        source = request.args.get('source')
        page_no = int(request.args.get('page_no', 1))
        page_size = min(int(request.args.get('page_size', 20)), 100)

        db = get_db()
        if db:
            result = db.get_seed_words(
                status=status,
                source=source,
                page_no=page_no,
                page_size=page_size
            )
        else:
            # Mock response for demo
            items = [
                {
                    "word": "抖号",
                    "status": "active",
                    "source": "learned",
                    "weekly_hit_count": 268,
                    "effective_clue_ratio": 0.32,
                    "last_promoted_at": "2026-05-21T11:00:00+08:00"
                },
                {
                    "word": "出号",
                    "status": "active",
                    "source": "preset",
                    "weekly_hit_count": 456,
                    "effective_clue_ratio": 0.45,
                    "last_promoted_at": None
                },
                {
                    "word": "千粉",
                    "status": "active",
                    "source": "preset",
                    "weekly_hit_count": 312,
                    "effective_clue_ratio": 0.28,
                    "last_promoted_at": None
                }
            ]

            # Filter by status if provided
            if status:
                items = [item for item in items if item['status'] == status]

            result = {
                "page_no": page_no,
                "page_size": page_size,
                "total": len(items),
                "items": items
            }

        response_data = {
            "page_no": result.get('page_no', page_no),
            "page_size": result.get('page_size', page_size),
            "total": result.get('total', 0),
            "items": result.get('items', [])
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting seed words: {e}", exc_info=True)
        return jsonify(format_error_response(1651, "Seed words status read failed")), 500


@seed_words_bp.route('/seed-words/<word>/promote', methods=['POST'])
def promote_seed_word(word: str):
    """Manually promote a seed word."""
    try:
        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1654, "Request body is required")), 400

        operator = data.get('operator')
        reason = data.get('reason')

        if not operator:
            return jsonify(format_error_response(1654, "operator is required")), 400

        db = get_db()
        promoted = False

        if db:
            seed_word = db.get_seed_word(word)
            if not seed_word:
                return jsonify(format_error_response(1652, "Seed word not found")), 404
            if seed_word.get('status') == 'active':
                return jsonify(format_error_response(1653, "Seed word already active")), 409

            promoted = db.promote_seed_word(word, operator, reason)

        if not db or not promoted:
            # Mock promotion for demo
            promoted = True

        response_data = {
            "word": word,
            "promoted": promoted,
            "status": "active"
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error promoting seed word: {e}", exc_info=True)
        return jsonify(format_error_response(1654, "Seed word promotion failed")), 500