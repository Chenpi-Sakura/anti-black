"""
Clue APIs for AntiBlack system.
Handles clue list retrieval and detail viewing.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id

logger = logging.getLogger(__name__)
clues_bp = Blueprint('clues', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@clues_bp.route('/clues', methods=['GET'])
def get_clues():
    """Get clue list with filtering and pagination."""
    try:
        # Parse query parameters
        query_id = request.args.get('query_id')
        page_no = int(request.args.get('page_no', 1))
        page_size = min(int(request.args.get('page_size', 10)), 100)
        risk_label_level1 = request.args.get('risk_label_level1')
        risk_label_level2 = request.args.get('risk_label_level2')
        source_channel = request.args.get('source_channel')
        entity_type = request.args.get('entity_type')
        min_confidence = request.args.get('min_confidence', type=float)
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')
        sort_by = request.args.get('sort_by', 'published_at')
        sort_order = request.args.get('sort_order', 'desc')

        # Validate sort field
        allowed_sort_fields = ['published_at', 'confidence', 'relation_count']
        if sort_by not in allowed_sort_fields:
            return jsonify(format_error_response(1302, "Unsupported sort field")), 400

        # Validate pagination
        if page_no < 1:
            return jsonify(format_error_response(1301, "Invalid page number")), 400
        if page_size < 1 or page_size > 100:
            return jsonify(format_error_response(1301, "Invalid page size")), 400

        # Get from database
        db = get_db()
        if db:
            result = db.get_clues(
                query_id=query_id,
                risk_label_level1=risk_label_level1,
                risk_label_level2=risk_label_level2,
                source_channel=source_channel,
                entity_type=entity_type,
                min_confidence=min_confidence,
                start_time=start_time,
                end_time=end_time,
                sort_by=sort_by,
                sort_order=-1 if sort_order == 'desc' else 1,
                page_no=page_no,
                page_size=page_size
            )
        else:
            # Mock response for demo
            result = _generate_mock_clues(page_no, page_size, risk_label_level1)

        # Format response
        items = []
        for clue in result.get('items', []):
            items.append({
                "clue_id": clue.get('clue_id', generate_id("clue")),
                "risk_label_level1": clue.get('risk_label_level1', '账号交易'),
                "risk_label_level2": clue.get('risk_label_level2', '抖音号买卖'),
                "confidence": clue.get('confidence', 0.9),
                "classification_source": clue.get('classification_source', 'rule'),
                "entity_summary": clue.get('entity_summary', []),
                "relation_count": clue.get('relation_count', 0),
                "source_channel": clue.get('source_channel', 'telegram'),
                "source_group_id": clue.get('source_group_id'),
                "platform": clue.get('platform'),
                "published_at": clue.get('published_at')
            })

        response_data = {
            "page_no": result.get('page_no', page_no),
            "page_size": result.get('page_size', page_size),
            "total": result.get('total', len(items)),
            "items": items
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting clues: {e}", exc_info=True)
        return jsonify(format_error_response(1303, "Clue retrieval failed")), 500


@clues_bp.route('/clues/<clue_id>', methods=['GET'])
def get_clue_detail(clue_id: str):
    """Get detailed information about a specific clue."""
    try:
        db = get_db()
        clue_data = None

        if db:
            clue_data = db.get_clue(clue_id)

        # If not found in DB, generate mock response
        if not clue_data:
            clue_data = _generate_mock_clue_detail(clue_id)

        # Format response
        response_data = {
            "clue_id": clue_data.get('clue_id', clue_id),
            "message_id": clue_data.get('message_id', generate_id("msg")),
            "risk_label_level1": clue_data.get('risk_label_level1', '账号交易'),
            "risk_label_level2": clue_data.get('risk_label_level2', '抖音号买卖'),
            "confidence": clue_data.get('confidence', 0.95),
            "classification_source": clue_data.get('classification_source', 'rule'),
            "classification_reason": clue_data.get('classification_reason', '命中关键词"出号""换绑"'),
            "source_channel": clue_data.get('source_channel', 'telegram'),
            "source_group_id": clue_data.get('source_group_id', 'tg_group_001'),
            "source_author_id": clue_data.get('source_author_id', 'tg_user_9527'),
            "raw_text": clue_data.get('raw_text', '出抖号，千粉，换绑稳，加V:dyhao668'),
            "cleaned_text": clue_data.get('cleaned_text', '出抖号 千粉 换绑稳 加V dyhao668'),
            "entity_list": clue_data.get('entity_list', [
                {
                    "entity_id": generate_id("ent"),
                    "entity_type": "WECHAT",
                    "entity_value": "dyhao668",
                    "source": "regex"
                }
            ]),
            "slang_mappings": clue_data.get('slang_mappings', [
                {"slang_raw": "抖号", "meaning": "抖音账号"}
            ]),
            "graph_relations": clue_data.get('graph_relations', [
                {
                    "related_entity_id": generate_id("ent"),
                    "related_entity_type": "URL",
                    "relation_type": "使用",
                    "confidence": 0.88,
                    "evidence": "同一消息中共同出现"
                }
            ]),
            "published_at": clue_data.get('published_at', datetime.utcnow().isoformat())
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting clue detail: {e}", exc_info=True)
        return jsonify(format_error_response(1402, "Clue detail retrieval failed")), 500


def _generate_mock_clues(page_no: int, page_size: int, risk_label_level1: str = None) -> dict:
    """Generate mock clues for demo."""
    items = []
    total = 17 if not risk_label_level1 else 8

    for i in range(min(page_size, total - (page_no - 1) * page_size)):
        items.append({
            "clue_id": generate_id("clue"),
            "risk_label_level1": risk_label_level1 or '账号交易',
            "risk_label_level2": '抖音号买卖',
            "confidence": 0.95 - i * 0.05,
            "classification_source": "rule",
            "entity_summary": [f"微信号: dyhao66{i}"],
            "relation_count": 4 - i,
            "source_channel": "telegram",
            "source_group_id": "tg_group_001",
            "platform": "抖音",
            "published_at": datetime.utcnow().isoformat()
        })

    return {
        "page_no": page_no,
        "page_size": page_size,
        "total": total,
        "items": items
    }


def _generate_mock_clue_detail(clue_id: str) -> dict:
    """Generate mock clue detail for demo."""
    return {
        "clue_id": clue_id,
        "message_id": generate_id("msg"),
        "risk_label_level1": "账号交易",
        "risk_label_level2": "抖音号买卖",
        "confidence": 0.95,
        "classification_source": "rule",
        "classification_reason": '命中关键词"出号""换绑"',
        "source_channel": "telegram",
        "source_group_id": "tg_group_001",
        "source_author_id": "tg_user_9527",
        "raw_text": "出抖号，千粉，换绑稳，加V:dyhao668",
        "cleaned_text": "出抖号 千粉 换绑稳 加V dyhao668",
        "entity_list": [
            {
                "entity_id": generate_id("ent"),
                "entity_type": "WECHAT",
                "entity_value": "dyhao668",
                "source": "regex"
            }
        ],
        "slang_mappings": [
            {"slang_raw": "抖号", "meaning": "抖音账号"}
        ],
        "graph_relations": [
            {
                "related_entity_id": generate_id("ent"),
                "related_entity_type": "URL",
                "relation_type": "使用",
                "confidence": 0.88,
                "evidence": "同一消息中共同出现"
            }
        ],
        "published_at": datetime.utcnow().isoformat()
    }