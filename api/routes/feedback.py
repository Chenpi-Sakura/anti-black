"""
Feedback API routes
"""
from fastapi import APIRouter, Depends, HTTPException
from api.schemas.feedback import FeedbackCreate
from api.deps import get_db
from models.entities import Feedback
from utils import generate_id, format_success_response

router = APIRouter(prefix="/feedback", tags=["反馈"])


@router.post("", response_model=dict, status_code=201)
def submit_feedback(
    data: FeedbackCreate,
    db=Depends(get_db)
):
    """Submit user feedback for a clue."""
    if not data.clue_id:
        raise HTTPException(status_code=400, detail="clue_id is required")

    feedback = Feedback(
        feedback_id=generate_id("fb"),
        clue_id=data.clue_id,
        feedback_type=data.feedback_type,
        correct_risk_label_level1=data.correct_risk_label_level1,
        correct_risk_label_level2=data.correct_risk_label_level2,
        correct_entities=data.correct_entities,
        comment=data.comment,
        operator=data.operator,
        platinum_enrolled=data.platinum_enrolled,
        sample_weight=data.sample_weight
    )

    db.insert_feedback(feedback)

    return format_success_response({
        "feedback_id": feedback.feedback_id,
        "message": "Feedback submitted successfully",
        "platinum_enrolled": data.platinum_enrolled
    })