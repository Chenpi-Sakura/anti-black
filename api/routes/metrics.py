"""
Metrics API routes
"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/metrics", tags=["监控"])


@router.get("/overview", response_model=dict)
def get_metrics_overview(db=Depends(get_db)):
    """Get system metrics overview."""
    metrics = db.get_latest_metrics()

    if not metrics:
        return format_success_response({
            "date": "",
            "token_usage_today": 0,
            "token_remaining_percent": 1.0,
            "collection_success_rate": 1.0,
            "total_entities": 0,
            "total_relations": 0,
            "messages_processed_today": 0,
            "classification_distribution": []
        })

    return format_success_response(metrics)