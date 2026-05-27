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
async def create_query(
    data: QueryCreate,
    db=Depends(get_db)
):
    """Create a new query task and start async orchestrator."""
    query_id = generate_id("qry")

    # Create query task
    from models.entities import QueryTask, QueryStatus
    task = QueryTask(
        query_id=query_id,
        query_text=data.query_text,
        status=QueryStatus.PENDING,
        parsed_intent=None,
        execution_plan=None,
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

    # Start async orchestrator task (non-blocking)
    asyncio.create_task(_run_orchestrator(query_id, data))

    return format_success_response({
        "query_id": query_id,
        "status": "PROCESSING"
    })


async def _run_orchestrator(query_id: str, data: QueryCreate):
    """Run orchestrator in background and push progress to SSE queue."""
    from services.orchestrator import Orchestrator

    try:
        orchestrator = Orchestrator()

        # Call the orchestrator (it pushes events via put_progress internally)
        await orchestrator.process_query(
            query_id=query_id,
            query_text=data.query_text,
            context=[],  # TODO: 支持多轮对话
            realtime_fetch=data.realtime_fetch,
            channels=data.channels or ['douyin', 'baidu_tieba'],
            time_range=data.time_range,
            risk_types=data.risk_types,
            platforms=data.platforms
        )

    except Exception as e:
        put_progress(query_id, {
            "type": "error",
            "content": f"处理失败: {str(e)}"
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
    - data: optional payload (e.g., clue list)
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