"""
Export API routes
"""
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db
from models import ExportTask
from utils import generate_id, format_success_response

router = APIRouter(prefix="/exports", tags=["导出"])


@router.post("", response_model=dict, status_code=201)
def create_export_task(data: dict, db=Depends(get_db)):
    """Create an export task."""
    task = ExportTask(
        export_id=generate_id("exp"),
        query_id=data.get("query_id"),
        filters=data.get("filters", {}),
        export_format=data.get("export_format", "json"),
        include_graph_relations=data.get("include_graph_relations", False),
        operator=data.get("operator", "")
    )

    db.create_export_task(task)

    return format_success_response({
        "export_id": task.export_id,
        "status": "PENDING"
    })


@router.get("/{export_id}", response_model=dict)
def get_export_task(export_id: str, db=Depends(get_db)):
    """Get export task status."""
    task = db.get_export_task(export_id)

    if not task:
        return format_success_response({
            "export_id": export_id,
            "status": "NOT_FOUND"
        })

    return format_success_response(task)