"""
Taxonomy API routes
"""
from fastapi import APIRouter
from api.deps import get_db
from config import get_config
from utils import format_success_response

router = APIRouter(prefix="/taxonomy", tags=["分类体系"])


@router.get("", response_model=dict)
def get_taxonomy():
    """Get classification taxonomy."""
    config = get_config()
    taxonomy = config.taxonomy
    return format_success_response(taxonomy)