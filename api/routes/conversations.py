"""
Conversation API routes for persistent chat history
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from utils import generate_id, format_success_response

router = APIRouter(prefix="/conversations", tags=["对话"])


class ConversationCreate(BaseModel):
    title: str = ""
    messages: list = []
    timeline: list = []


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    messages: Optional[list] = None
    timeline: Optional[list] = None


@router.post("", response_model=dict, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    db=Depends(get_db)
):
    """Create a new conversation."""
    conversation_id = generate_id("conv")

    from models.entities import Conversation
    conversation = Conversation(
        conversation_id=conversation_id,
        title=data.title,
        messages=data.messages,
        timeline=data.timeline,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.create_conversation(conversation)

    return format_success_response({
        "conversation_id": conversation_id,
        "created_at": conversation.created_at.isoformat()
    })


@router.get("", response_model=dict)
async def list_conversations(
    limit: int = 50,
    db=Depends(get_db)
):
    """List all conversations ordered by created_at desc."""
    conversations = db.list_conversations(limit=limit)

    # Convert datetime to ISO format
    for conv in conversations:
        if conv.get('created_at'):
            conv['created_at'] = conv['created_at'].isoformat() if hasattr(conv['created_at'], 'isoformat') else str(conv['created_at'])
        if conv.get('updated_at'):
            conv['updated_at'] = conv['updated_at'].isoformat() if hasattr(conv['updated_at'], 'isoformat') else str(conv['updated_at'])

    return format_success_response(conversations)


@router.get("/{conversation_id}", response_model=dict)
async def get_conversation(
    conversation_id: str,
    db=Depends(get_db)
):
    """Get a conversation by ID."""
    conversation = db.get_conversation(conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Convert datetime to ISO format
    for dt_field in ['created_at', 'updated_at']:
        if conversation.get(dt_field) and hasattr(conversation[dt_field], 'isoformat'):
            conversation[dt_field] = conversation[dt_field].isoformat()

    return format_success_response(conversation)


@router.put("/{conversation_id}", response_model=dict)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    db=Depends(get_db)
):
    """Update a conversation."""
    conversation = db.get_conversation(conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.update_conversation(
        conversation_id=conversation_id,
        messages=data.messages,
        timeline=data.timeline,
        title=data.title
    )

    return format_success_response({"conversation_id": conversation_id, "status": "updated"})