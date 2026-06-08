"""
Feedback API routes
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from api.schemas.feedback import FeedbackCreate
from api.deps import get_db
from models import Feedback
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


@router.get("", response_model=dict)
def list_feedbacks(
    feedback_type: Optional[str] = Query(default=None, description="反馈类型"),
    clue_id: Optional[str] = Query(default=None, description="线索ID"),
    platinum_enrolled: Optional[bool] = Query(default=None, description="铂金样本"),
    model_update_status: Optional[str] = Query(default=None, description="模型更新状态"),
    operator: Optional[str] = Query(default=None, description="操作人"),
    start_time: Optional[str] = Query(default=None, description="开始时间"),
    end_time: Optional[str] = Query(default=None, description="结束时间"),
    sort_by: str = Query(default="created_at", description="排序字段"),
    sort_order: int = Query(default=-1, description="排序方向: -1降序, 1升序"),
    page_no: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db=Depends(get_db)
):
    """List feedback with filtering, sorting, and pagination.

    Mirrors the clues.py list endpoint style — explicit Query(...) parameters
    (not Pydantic QueryParams) following project convention.
    """
    result = db.list_feedbacks(
        feedback_type=feedback_type,
        clue_id=clue_id,
        platinum_enrolled=platinum_enrolled,
        model_update_status=model_update_status,
        operator=operator,
        start_time=start_time,
        end_time=end_time,
        sort_by=sort_by,
        sort_order=sort_order,
        page_no=page_no,
        page_size=page_size
    )

    return format_success_response(result)