"""
Channels API routes
"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from utils import format_success_response

router = APIRouter(prefix="/channels", tags=["渠道"])


@router.get("", response_model=dict)
def get_channels(db=Depends(get_db)):
    """Get all channels."""
    channels = db.get_all_channels()
    return format_success_response(channels)


@router.get("/{platform}/status", response_model=dict)
def get_channel_status(platform: str, db=Depends(get_db)):
    """Get channel status."""
    channel = db.get_channel(platform)

    if not channel:
        return format_success_response({
            "platform": platform,
            "status": "unknown"
        })

    return format_success_response(channel)