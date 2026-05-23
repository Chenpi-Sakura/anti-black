"""
Channel APIs for AntiBlack system.
Handles channel configuration and status.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from config import get_config
from utils import format_success_response, format_error_response, generate_id
from models import Channel

logger = logging.getLogger(__name__)
channels_bp = Blueprint('channels', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@channels_bp.route('/channels', methods=['GET'])
def get_channels():
    """Get all channels with optional filtering."""
    try:
        category = request.args.get('category')

        db = get_db()
        if db:
            channels = db.get_all_channels(category)
        else:
            # Mock response for demo
            channels = [
                {
                    "platform": "telegram",
                    "platform_name": "Telegram",
                    "category": "im",
                    "status": "connected",
                    "enabled": True,
                    "configured_at": datetime.utcnow().isoformat(),
                    "messages_today": 486
                },
                {
                    "platform": "x",
                    "platform_name": "X (Twitter)",
                    "category": "im",
                    "status": "connected",
                    "enabled": True,
                    "configured_at": datetime.utcnow().isoformat(),
                    "messages_today": 128
                },
                {
                    "platform": "baidu_tieba",
                    "platform_name": "百度贴吧",
                    "category": "social",
                    "status": "connected",
                    "enabled": True,
                    "configured_at": datetime.utcnow().isoformat(),
                    "messages_today": 320
                },
                {
                    "platform": "douyin",
                    "platform_name": "抖音",
                    "category": "social",
                    "status": "unconfigured",
                    "enabled": False,
                    "configured_at": None,
                    "messages_today": 0
                }
            ]

        response_data = {
            "items": channels
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting channels: {e}", exc_info=True)
        return jsonify(format_error_response(1951, "Channel list read failed")), 500


@channels_bp.route('/channels/<platform>/status', methods=['GET'])
def get_channel_status(platform: str):
    """Get detailed status of a specific channel."""
    try:
        # Validate platform
        supported_platforms = ['telegram', 'x', 'baidu_tieba', 'douyin', 'rednote',
                               'secondhand', 'zhilian', 'darkweb', 'tech_forum']
        if platform not in supported_platforms:
            return jsonify(format_error_response(1960, "Unsupported platform")), 400

        db = get_db()
        channel_data = None

        if db:
            channel_data = db.get_channel(platform)

        if not channel_data:
            # Mock response for demo
            channel_data = _generate_mock_channel_status(platform)

        return jsonify(format_success_response(channel_data))

    except Exception as e:
        logger.error(f"Error getting channel status: {e}", exc_info=True)
        return jsonify(format_error_response(1951, "Channel status read failed")), 500


@channels_bp.route('/channels/<platform>/config', methods=['POST'])
def configure_channel(platform: str):
    """Configure a channel."""
    try:
        # Validate platform
        supported_platforms = ['telegram', 'x', 'baidu_tieba', 'douyin', 'rednote',
                               'secondhand', 'zhilian', 'darkweb', 'tech_forum']
        if platform not in supported_platforms:
            return jsonify(format_error_response(1960, "Unsupported platform")), 400

        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1952, "Request body is required")), 400

        config_data = data.get('config', {})
        operator = data.get('operator')

        if not operator:
            return jsonify(format_error_response(1952, "operator is required")), 400

        # Validate required fields per platform
        if platform == 'telegram':
            if not config_data.get('bot_token'):
                return jsonify(format_error_response(1952, "bot_token is required for telegram")), 400
            if not config_data.get('chat_ids'):
                return jsonify(format_error_response(1952, "chat_ids is required for telegram")), 400

        # Create or update channel
        channel = Channel(
            platform=platform,
            platform_name=_get_platform_name(platform),
            category=_get_platform_category(platform),
            status="connected",
            enabled=data.get('enabled', True),
            config=config_data,
            configured_at=datetime.utcnow(),
            messages_today=0
        )

        db = get_db()
        if db:
            db.upsert_channel(channel)

        response_data = {
            "platform": platform,
            "configured_items": len(config_data.get('chat_ids', [])),
            "configured_keywords": len(config_data.get('keywords', [])),
            "status": "APPLIED"
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error configuring channel: {e}", exc_info=True)
        return jsonify(format_error_response(1954, "Channel configuration update failed")), 500


@channels_bp.route('/channels/<platform>/stats', methods=['GET'])
def get_channel_stats(platform: str):
    """Get statistics for a channel."""
    try:
        time_range = request.args.get('time_range', 'today')

        # Mock response for demo
        response_data = {
            "platform": platform,
            "total_messages_collected": 15230,
            "messages_in_period": 486,
            "success_rate": 0.98,
            "avg_latency_ms": 320,
            "error_breakdown": [
                {"error_type": "rate_limit", "count": 3},
                {"error_type": "auth_error", "count": 1}
            ],
            "time_series": [
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "messages_count": 42,
                    "errors_count": 1
                }
            ]
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting channel stats: {e}", exc_info=True)
        return jsonify(format_error_response(1955, "Channel stats read failed")), 500


def _get_platform_name(platform: str) -> str:
    """Get human-readable platform name."""
    names = {
        'telegram': 'Telegram',
        'x': 'X (Twitter)',
        'baidu_tieba': '百度贴吧',
        'douyin': '抖音',
        'rednote': '小红书',
        'secondhand': '闲鱼/转转',
        'zhilian': '智联/猎聘',
        'darkweb': '暗网',
        'tech_forum': '技术交流社区'
    }
    return names.get(platform, platform)


def _get_platform_category(platform: str) -> str:
    """Get platform category."""
    categories = {
        'telegram': 'im',
        'x': 'im',
        'baidu_tieba': 'social',
        'douyin': 'social',
        'rednote': 'social',
        'secondhand': 'vertical',
        'zhilian': 'vertical',
        'darkweb': 'vertical',
        'tech_forum': 'vertical'
    }
    return categories.get(platform, 'im')


def _generate_mock_channel_status(platform: str) -> dict:
    """Generate mock channel status for demo."""
    return {
        "platform": platform,
        "platform_name": _get_platform_name(platform),
        "status": "connected",
        "enabled": True,
        "config": {
            "keywords": ["出号", "换绑", "抖号"],
            "exclude_keywords": ["测试", "广告"],
            "collection_interval_seconds": 60
        },
        "platform_specific": {
            "bot_username": "@anti_black_bot",
            "authorized_chats": [
                {
                    "chat_id": "-1001234567890",
                    "title": "黑产交易群A",
                    "members_count": 256,
                    "is_active": True
                }
            ]
        },
        "last_polling_at": datetime.utcnow().isoformat(),
        "error_message": None
    }