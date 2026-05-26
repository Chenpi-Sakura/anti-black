"""
Query API routes with SSE streaming support
"""
import json
import asyncio
from asyncio import Queue
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime

from api.schemas.queries import QueryCreate, QueryResponse
from api.deps import get_db
from utils import generate_id, format_success_response

router = APIRouter(prefix="/queries", tags=["查询"])

# Progress queue for SSE streaming
_progress_queues: dict[str, Queue] = {}


def get_progress_queue(query_id: str) -> Queue:
    """Get or create progress queue for a query."""
    if query_id not in _progress_queues:
        _progress_queues[query_id] = Queue()
    return _progress_queues[query_id]


def put_progress(query_id: str, event: dict) -> None:
    """Put progress event into queue (called by background pipeline)."""
    queue = _progress_queues.get(query_id)
    if queue:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


@router.post("", response_model=dict, status_code=201)
def create_query(
    data: QueryCreate,
    db=Depends(get_db)
):
    """Create a new query task."""
    query_id = generate_id("qry")

    # Parse intent from query text
    parsed_intent = _parse_intent(data.query_text)

    # Create execution plan
    execution_plan = _create_execution_plan(data)

    # Create query task
    from models.entities import QueryTask, QueryStatus
    task = QueryTask(
        query_id=query_id,
        query_text=data.query_text,
        status=QueryStatus.PENDING,
        parsed_intent=parsed_intent,
        execution_plan=execution_plan,
        realtime_fetch=data.realtime_fetch,
        channels=data.channels,
        time_range=data.time_range,
        risk_types=data.risk_types,
        platforms=data.platforms,
        progress=0
    )

    # Save to database
    db.create_query_task(task)

    # Initialize progress queue for SSE
    get_progress_queue(query_id)

    return format_success_response({
        "query_id": query_id,
        "status": "PENDING",
        "parsed_intent": parsed_intent
    })


@router.get("/{query_id}", response_model=dict)
def get_query_status(
    query_id: str,
    db=Depends(get_db)
):
    """Get query task status."""
    task_data = db.get_query_task(query_id)

    if not task_data:
        raise HTTPException(status_code=404, detail="Query not found")

    return format_success_response(task_data)


@router.get("/{query_id}/stream")
async def stream_query_status(query_id: str):
    """
    SSE stream for query progress.

    Format: each message is JSON with fields:
    - type: stage|progress|content|complete|heartbeat|error
    - stage: stage identifier
    - content: display content
    - progress: 0-100
    """
    async def event_generator():
        queue = get_progress_queue(query_id)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"

                if event.get("type") == "complete":
                    break
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            except asyncio.CancelledError:
                break

        # Cleanup
        _progress_queues.pop(query_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


def _parse_intent(query_text: str) -> dict:
    """Parse intent from query text."""
    from utils import parse_time_range, parse_platform, parse_risk_type

    start_time, end_time = parse_time_range(query_text)
    platforms = parse_platform(query_text)
    risk_types = parse_risk_type(query_text)
    keywords = _extract_keywords(query_text)

    time_range = {}
    if start_time:
        time_range['start_time'] = start_time
    if end_time:
        time_range['end_time'] = end_time

    return {
        "time_range": time_range if time_range else None,
        "risk_types": risk_types,
        "platforms": platforms,
        "keywords": keywords
    }


def _extract_keywords(text: str) -> list[str]:
    """Extract business keywords from query text."""
    keyword_patterns = [
        r'出号', r'换绑', r'租号', r'千粉', r'万粉',
        r'加V', r'微信号', r'抖音号', r'快手号',
        r'刷粉', r'刷赞', r'刷量', r'接码',
        r'群控', r'脚本', r'养号'
    ]

    keywords = []
    for pattern in keyword_patterns:
        if pattern in text:
            keywords.append(pattern)

    return keywords


def _create_execution_plan(data: QueryCreate) -> dict:
    """Create execution plan based on request."""
    channels = data.channels if data.channels else ['telegram', 'forum']
    fetch_mode = 'local_plus_realtime' if data.realtime_fetch else 'local_only'

    return {
        "fetch_mode": fetch_mode,
        "target_channels": channels,
        "estimated_cost_level": "medium",
        "estimated_finish_seconds": 120
    }