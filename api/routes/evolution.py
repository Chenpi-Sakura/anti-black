"""
Evolution API routes
"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/evolution", tags=["自进化"])


@router.get("/status", response_model=dict)
def get_evolution_status(db=Depends(get_db)):
    """Get auto evolution status."""
    status = db.get_auto_evolution_status()
    return format_success_response(status)


@router.get("/proposals", response_model=dict)
def get_proposals(
    proposal_type: str = None,
    status: str = None,
    page_no: int = 1,
    page_size: int = 20,
    db=Depends(get_db)
):
    """Get rule proposals."""
    result = db.get_proposals(proposal_type, status, page_no, page_size)
    return format_success_response(result)


@router.post("/proposals/{proposal_id}/approve", response_model=dict)
def approve_proposal(proposal_id: str, db=Depends(get_db)):
    """Approve a proposal."""
    db.approve_proposal(proposal_id, operator='admin', comment=None)
    return format_success_response({"proposal_id": proposal_id, "approved": True})