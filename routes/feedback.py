"""
Feedback APIs for AntiBlack system.
Handles user feedback for corrections.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from utils import format_success_response, format_error_response, generate_id
from models import Feedback

logger = logging.getLogger(__name__)
feedback_bp = Blueprint('feedback', __name__)


def get_db():
    """Get database service from app config."""
    return current_app.config.get('db')


@feedback_bp.route('/feedback', methods=['POST'])
def submit_feedback():
    """Submit user feedback for clue correction."""
    try:
        data = request.get_json()
        if not data:
            return jsonify(format_error_response(1601, "Request body is required")), 400

        # Validate required fields
        clue_id = data.get('clue_id')
        feedback_type = data.get('feedback_type')
        operator = data.get('operator')

        if not clue_id:
            return jsonify(format_error_response(1602, "clue_id is required")), 400
        if not feedback_type:
            return jsonify(format_error_response(1601, "feedback_type is required")), 400
        if not operator:
            return jsonify(format_error_response(1601, "operator is required")), 400

        # Validate feedback type
        valid_feedback_types = ['classification_error', 'entity_error', 'normal_message']
        if feedback_type not in valid_feedback_types:
            return jsonify(format_error_response(1601, "Invalid feedback_type")), 400

        # Generate feedback ID
        feedback_id = generate_id("fb")

        # Check if clue exists
        db = get_db()
        clue_exists = False
        if db:
            clue = db.get_clue(clue_id)
            clue_exists = clue is not None

        if not clue_exists and not db:
            # Mock: accept feedback for demo
            pass

        # Create feedback record
        feedback = Feedback(
            feedback_id=feedback_id,
            clue_id=clue_id,
            feedback_type=feedback_type,
            correct_risk_label_level1=data.get('correct_risk_label_level1'),
            correct_risk_label_level2=data.get('correct_risk_label_level2'),
            correct_entities=data.get('correct_entities', []),
            comment=data.get('comment'),
            operator=operator,
            platinum_enrolled=(feedback_type == 'classification_error'),
            sample_weight=10 if feedback_type == 'classification_error' else 1,
            model_update_status='QUEUED' if feedback_type == 'classification_error' else 'IDLE'
        )

        # Save to database
        if db:
            db.insert_feedback(feedback)

        # Build response
        response_data = {
            "feedback_id": feedback_id,
            "accepted": True,
            "queued_for_evolution": feedback_type == 'classification_error',
            "platinum_enrolled": feedback.platinum_enrolled,
            "sample_weight": feedback.sample_weight,
            "model_update_status": feedback.model_update_status
        }

        return jsonify(format_success_response(response_data)), 201

    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        return jsonify(format_error_response(1604, "Feedback submission failed")), 500