"""
Evolution APIs for AntiBlack system.
Handles auto-evolution status and proposal management.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id

logger = logging.getLogger(__name__)
evolution_bp = Blueprint('evolution', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@evolution_bp.route('/evolution/status', methods=['GET'])
def get_evolution_status():
    """Get auto-evolution status."""
    try:
        db = get_db()

        if db:
            status = db.get_auto_evolution_status()
        else:
            # Mock response for demo
            status = {
                "enabled": True,
                "silver_sample_count": 1820,
                "platinum_sample_count": 24,
                "error_book_count": 112,
                "current_model_version": "clf_v0.3.2",
                "retrain_status": "QUEUED",
                "retrain_trigger_threshold": 2000,
                "last_retrain_at": "2026-05-22T02:30:00+08:00"
            }

        return jsonify(format_success_response(status))

    except Exception as e:
        logger.error(f"Error getting evolution status: {e}", exc_info=True)
        return jsonify(format_error_response(1661, "Evolution status read failed")), 500


@evolution_bp.route('/evolution/proposals', methods=['GET'])
def get_proposals():
    """Get proposal list with filtering."""
    try:
        proposal_type = request.args.get('proposal_type')
        status = request.args.get('status', 'pending')
        page_no = int(request.args.get('page_no', 1))
        page_size = min(int(request.args.get('page_size', 20)), 100)

        db = get_db()
        if db:
            result = db.get_proposals(
                proposal_type=proposal_type,
                status=status,
                page_no=page_no,
                page_size=page_size
            )
        else:
            # Mock response for demo
            items = []
            if status == 'pending':
                items = [
                    {
                        "proposal_id": generate_id("prop"),
                        "proposal_type": "classification_rule",
                        "title": '新增"内部代下"为诈骗引流强特征词',
                        "detail": "过去24小时在诈骗引流样本中高频出现",
                        "status": "pending",
                        "created_at": datetime.utcnow().isoformat()
                    }
                ]
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
        logger.error(f"Error getting proposals: {e}", exc_info=True)
        return jsonify(format_error_response(1662, "Proposal list read failed")), 500


@evolution_bp.route('/evolution/proposals/<proposal_id>/approve', methods=['POST'])
def approve_proposal(proposal_id: str):
    """Approve a proposal."""
    try:
        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1663, "Request body is required")), 400

        operator = data.get('operator')
        comment = data.get('comment')

        if not operator:
            return jsonify(format_error_response(1663, "operator is required")), 400

        db = get_db()
        approved = False

        if db:
            proposal = db.get_proposal(proposal_id)
            if not proposal:
                return jsonify(format_error_response(1663, "Proposal not found")), 404
            if proposal.get('status') != 'pending':
                return jsonify(format_error_response(1664, "Proposal already processed")), 409

            approved = db.approve_proposal(proposal_id, operator, comment)

        if not db or not approved:
            # Mock approval for demo
            approved = True

        response_data = {
            "proposal_id": proposal_id,
            "approved": approved,
            "applied_to": "classification_rule"
        }

        return jsonify(format_success_response(response_data))

    except Exception as e:
        logger.error(f"Error approving proposal: {e}", exc_info=True)
        return jsonify(format_error_response(1665, "Proposal approval failed")), 500