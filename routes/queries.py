"""
Query APIs for AntiBlack system.
Handles natural language query creation and status tracking.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from config import get_config
from utils import format_success_response, format_error_response, generate_id
from models import QueryTask, QueryStatus

logger = logging.getLogger(__name__)
queries_bp = Blueprint('queries', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@queries_bp.route('/queries', methods=['POST'])
def create_query():
    """Create a new natural language query task."""
    try:
        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1001, "Request body is required")), 400

        query_text = data.get('query_text', '').strip()
        if not query_text:
            return jsonify(format_error_response(1001, "query_text is required")), 400

        # Generate query ID
        query_id = generate_id("qry")

        # Parse intent from query
        parsed_intent = _parse_intent(query_text, data)

        # Create execution plan
        execution_plan = _create_execution_plan(data, parsed_intent)

        # Create query task
        task = QueryTask(
            query_id=query_id,
            query_text=query_text,
            status=QueryStatus.PENDING,
            parsed_intent=parsed_intent,
            execution_plan=execution_plan,
            realtime_fetch=data.get('realtime_fetch', False),
            channels=data.get('channels', []),
            time_range=data.get('time_range'),
            risk_types=parsed_intent.get('risk_types', []),
            platforms=parsed_intent.get('platforms', []),
            constraints=data.get('constraints', {}),
            progress=0,
            result_stats={
                "raw_message_count": 0,
                "cleaned_message_count": 0,
                "classified_message_count": 0,
                "clue_count": 0,
                "deep_analysis_count": 0
            }
        )

        # Save to database
        db = get_db()
        if db:
            db.create_query_task(task)

        # Generate mock clue preview for demo
        clue_preview = _generate_mock_clue_preview(parsed_intent)

        # Build response
        response_data = {
            "query_id": query_id,
            "task_id": query_id,  # Compatibility alias
            "status": "PENDING",
            "parsed_intent": parsed_intent,
            "execution_plan": execution_plan,
            "summary": {
                "total_clues": len(clue_preview),
                "high_risk_clues": max(0, len(clue_preview) - 2),
                "processing_progress": 0,
                "source_hit_count": len(task.channels) if task.channels else 1
            },
            "clue_preview": clue_preview
        }

        return jsonify(format_success_response(response_data)), 201

    except Exception as e:
        logger.error(f"Error creating query: {e}", exc_info=True)
        return jsonify(format_error_response(1004, "Query task creation failed")), 500


@queries_bp.route('/queries/<query_id>', methods=['GET'])
def get_query_status(query_id: str):
    """Get query task status and progress."""
    try:
        db = get_db()
        task_data = None

        if db:
            task_data = db.get_query_task(query_id)

        # If not found in DB, generate mock response for demo
        if not task_data:
            task_data = {
                "query_id": query_id,
                "query_text": "Mock query",
                "status": "RUNNING",
                "progress": 65,
                "stage": "collecting",
                "message": "正在从 telegram 抓取增量消息",
                "result_stats": {
                    "raw_message_count": 126,
                    "cleaned_message_count": 88,
                    "classified_message_count": 80,
                    "clue_count": 17,
                    "deep_analysis_count": 5
                },
                "failure_reason": None,
                "updated_at": datetime.utcnow().isoformat()
            }

        response_data = {
            "query_id": task_data["query_id"],
            "task_id": task_data["query_id"],
            "status": task_data.get("status", "RUNNING"),
            "progress": task_data.get("progress", 100),
            "stage": task_data.get("stage"),
            "message": task_data.get("message"),
            "result_stats": task_data.get("result_stats", {}),
            "failure_reason": task_data.get("failure_reason"),
            "updated_at": task_data.get("updated_at")
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting query status: {e}", exc_info=True)
        return jsonify(format_error_response(1102, "Query task status read failed")), 500


def _parse_intent(query_text: str, data: dict) -> dict:
    """Parse user query to extract intent parameters."""
    from utils import parse_time_range, parse_platform, parse_risk_type

    # Parse time range
    start_time, end_time = parse_time_range(query_text)

    # If time_range provided in request, use it
    if data.get('time_range'):
        time_range = data['time_range']
    else:
        time_range = {}
        if start_time:
            time_range['start_time'] = start_time
        if end_time:
            time_range['end_time'] = end_time

    # Parse platforms
    platforms = parse_platform(query_text)
    if data.get('platforms'):
        platforms.extend(data['platforms'])
    platforms = list(set(platforms))

    # Parse risk types
    risk_types = parse_risk_type(query_text)
    if data.get('risk_types'):
        risk_types.extend(data['risk_types'])
    risk_types = list(set(risk_types))

    # Extract keywords from query text
    keywords = _extract_keywords(query_text)

    return {
        "time_range": time_range if time_range else None,
        "risk_types": risk_types,
        "platforms": platforms,
        "keywords": keywords
    }


def _extract_keywords(text: str) -> list:
    """Extract business keywords from query text."""
    # Common black market keywords
    keyword_patterns = [
        r'出号', r'换绑', r'租号', r'千粉', r'万粉',
        r'加V', r'微信号', r'抖音号', r'快手号',
        r'刷粉', r'刷赞', r'刷量', r'接码',
        r'群控', r'脚本', r'养号'
    ]

    keywords = []
    for pattern in keyword_patterns:
        if pattern in text:
            keywords.append(pattern)

    return keywords


def _create_execution_plan(data: dict, parsed_intent: dict) -> dict:
    """Create execution plan based on parsed intent."""
    channels = data.get('channels', [])
    if not channels:
        channels = ['telegram', 'forum']

    fetch_mode = 'local_only'
    if data.get('realtime_fetch'):
        fetch_mode = 'local_plus_realtime'

    return {
        "fetch_mode": fetch_mode,
        "target_channels": channels,
        "estimated_cost_level": "medium",
        "estimated_finish_seconds": 120
    }


def _generate_mock_clue_preview(parsed_intent: dict) -> list:
    """Generate mock clue preview for demo purposes."""
    risk_types = parsed_intent.get('risk_types', ['账号交易'])
    platforms = parsed_intent.get('platforms', ['抖音'])

    risk_label = risk_types[0] if risk_types else '账号交易'
    risk_label_level2 = '抖音号买卖' if '抖音' in str(platforms) else '账号买卖'

    return [
        {
            "clue_id": generate_id("clue"),
            "risk_label_level1": risk_label,
            "risk_label_level2": risk_label_level2,
            "confidence": 0.95,
            "entity_summary": ["微信号: dyhao668", "价格: 80元"],
            "source_channel": "telegram",
            "published_at": datetime.utcnow().isoformat()
        },
        {
            "clue_id": generate_id("clue"),
            "risk_label_level1": risk_label,
            "risk_label_level2": risk_label_level2,
            "confidence": 0.88,
            "entity_summary": ["微信号: brushdan001", "价格: 120元"],
            "source_channel": "telegram",
            "published_at": (datetime.utcnow()).isoformat()
        }
    ]