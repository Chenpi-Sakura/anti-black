"""
System API routes
"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/ready", response_model=dict)
def get_system_ready(db=Depends(get_db)):
    """Get system ready status."""
    status = db.get_system_ready_status()
    return format_success_response(status)


@router.get("/pipeline-status", response_model=dict)
def get_pipeline_status(db=Depends(get_db)):
    """Get background pipeline status."""
    status = db.get_pipeline_status()
    return format_success_response(status)