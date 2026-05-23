"""
Taxonomy APIs for AntiBlack system.
Handles risk classification taxonomy retrieval.
"""
import logging
from flask import Blueprint, request, jsonify

from config import get_config
from utils import format_success_response, format_error_response

logger = logging.getLogger(__name__)
taxonomy_bp = Blueprint('taxonomy', __name__)


@taxonomy_bp.route('/taxonomy', methods=['GET'])
def get_taxonomy():
    """Get current risk classification taxonomy."""
    try:
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'

        config = get_config()
        taxonomy = config.taxonomy

        # Format taxonomy for response
        categories = []
        for cat in taxonomy.get('categories', []):
            level1_code = cat.get('level1_code', '')
            level1_name = cat.get('level1_name', '')
            description = cat.get('description', '')

            level2_items = []
            for item in cat.get('level2_items', []):
                level2_items.append({
                    "level2_code": item.get('level2_code', ''),
                    "level2_name": item.get('level2_name', ''),
                    "enabled": True  # All items enabled by default
                })

            categories.append({
                "level1_code": level1_code,
                "level1_name": level1_name,
                "description": description,
                "level2_items": level2_items
            })

        response_data = {
            "version": taxonomy.get('version', 'taxonomy_v1'),
            "categories": categories
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting taxonomy: {e}", exc_info=True)
        return jsonify(format_error_response(1201, "Taxonomy loading failed")), 500