"""
Seed Words API routes
"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/seed-words", tags=["种子词"])


@router.get("", response_model=dict)
def get_seed_words(
    status: str = None,
    page_no: int = 1,
    page_size: int = 20,
    db=Depends(get_db)
):
    """Get seed words list."""
    result = db.get_seed_words(status=status, page_no=page_no, page_size=page_size)
    return format_success_response(result)


@router.post("/{word}/promote", response_model=dict)
def promote_seed_word(word: str, db=Depends(get_db)):
    """Promote a seed word to active."""
    db.promote_seed_word(word, operator='admin')
    return format_success_response({"word": word, "promoted": True})