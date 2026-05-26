"""
Entity API routes
"""
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/entities", tags=["实体"])


@router.get("/{entity_id}/profile", response_model=dict)
def get_entity_profile(
    entity_id: str,
    db=Depends(get_db)
):
    """Get entity profile with related entities."""
    profile = db.get_entity_profile(entity_id)

    if not profile:
        raise HTTPException(status_code=404, detail="Entity not found")

    return format_success_response(profile)


@router.get("", response_model=dict)
def get_entities(
    entity_type: str,
    limit: int = 100,
    db=Depends(get_db)
):
    """Get entities by type."""
    if not entity_type:
        raise HTTPException(status_code=400, detail="entity_type is required")

    entities = db.get_entities_by_type(entity_type, limit)

    return format_success_response({
        "entity_type": entity_type,
        "items": entities,
        "total": len(entities)
    })