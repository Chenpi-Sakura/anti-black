"""
Clue API routes
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from api.schemas.clues import ClueQueryParams, ClueResponse, ClueListResponse
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/clues", tags=["线索"])


@router.get("", response_model=dict)
def get_clues(
    query_id: Optional[str] = Query(default=None, description="查询ID"),
    risk_label_level1: Optional[str] = Query(default=None, description="一级风险标签"),
    risk_label_level2: Optional[str] = Query(default=None, description="二级风险标签"),
    source_channel: Optional[str] = Query(default=None, description="来源渠道"),
    min_confidence: float = Query(default=0, ge=0, le=1, description="最低置信度"),
    start_time: Optional[str] = Query(default=None, description="开始时间"),
    end_time: Optional[str] = Query(default=None, description="结束时间"),
    page_no: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页条数"),
    sort_by: str = Query(default="published_at", description="排序字段"),
    sort_order: int = Query(default=-1, description="排序方向"),
    db=Depends(get_db)
):
    """Get clues list with filtering and pagination."""
    result = db.get_clues(
        query_id=query_id,
        risk_label_level1=risk_label_level1,
        risk_label_level2=risk_label_level2,
        source_channel=source_channel,
        min_confidence=min_confidence,
        start_time=start_time,
        end_time=end_time,
        page_no=page_no,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order
    )

    return format_success_response(result)


@router.get("/{clue_id}", response_model=dict)
def get_clue(
    clue_id: str,
    db=Depends(get_db)
):
    """Get clue detail by ID."""
    clue = db.get_clue(clue_id)

    if not clue:
        raise HTTPException(status_code=404, detail="Clue not found")

    return format_success_response(clue)