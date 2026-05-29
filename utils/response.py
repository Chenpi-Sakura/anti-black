from typing import Any, Dict, Optional
from .helpers import generate_id


def format_error_response(code: int, message: str, request_id: Optional[str] = None) -> Dict[str, Any]:
    """Format error response."""
    return {
        "code": code,
        "message": message,
        "request_id": request_id or generate_id("req"),
        "data": None
    }


def format_success_response(data: Any, request_id: Optional[str] = None, message: str = "ok") -> Dict[str, Any]:
    """Format success response."""
    return {
        "code": 0,
        "message": message,
        "request_id": request_id or generate_id("req"),
        "data": data
    }
