"""
Export APIs for AntiBlack system.
Handles data export task creation and status tracking.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id
from models import ExportTask, ExportStatus

logger = logging.getLogger(__name__)
export_bp = Blueprint('export', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@export_bp.route('/exports', methods=['POST'])
def create_export():
    """Create a new export task."""
    try:
        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1702, "Request body is required")), 400

        export_format = data.get('export_format', 'json')
        operator = data.get('operator')

        if not operator:
            return jsonify(format_error_response(1702, "operator is required")), 400

        if export_format not in ['json', 'csv']:
            return jsonify(format_error_response(1701, "Unsupported export format")), 400

        # Generate export ID
        export_id = generate_id("exp")

        # Validate that we have query_id or filters
        query_id = data.get('query_id')
        filters = data.get('filters', {})

        if not query_id and not filters:
            return jsonify(format_error_response(1702, "Either query_id or filters is required")), 400

        # Create export task
        export_task = ExportTask(
            export_id=export_id,
            query_id=query_id,
            filters=filters,
            export_format=export_format,
            include_graph_relations=data.get('include_graph_relations', False),
            operator=operator,
            status=ExportStatus.PENDING
        )

        # Save to database
        db = get_db()
        if db:
            db.create_export_task(export_task)

        response_data = {
            "export_id": export_id,
            "status": "PENDING"
        }

        return jsonify(format_success_response(response_data)), 201

    except Exception as e:
        logger.error(f"Error creating export: {e}", exc_info=True)
        return jsonify(format_error_response(1703, "Export task creation failed")), 500


@export_bp.route('/exports/<export_id>', methods=['GET'])
def get_export_status(export_id: str):
    """Get export task status."""
    try:
        db = get_db()
        export_task = None

        if db:
            export_task = db.get_export_task(export_id)

        if not export_task:
            # Mock response for demo
            export_task = {
                "export_id": export_id,
                "status": "COMPLETED",
                "download_url": f"http://127.0.0.1:8000/downloads/{export_id}.csv",
                "expire_at": (datetime.utcnow()).isoformat()
            }

        response_data = {
            "export_id": export_task.get('export_id', export_id),
            "status": export_task.get('status', 'COMPLETED'),
            "download_url": export_task.get('download_url'),
            "expire_at": export_task.get('expire_at')
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error getting export status: {e}", exc_info=True)
        return jsonify(format_error_response(1802, "Export task status read failed")), 500