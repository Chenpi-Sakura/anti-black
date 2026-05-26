"""
Pydantic schemas for Query APIs
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class QueryCreate(BaseModel):
    """Request schema for creating a query."""
    query_text: str = Field(..., min_length=1, description="查询文本")
    realtime_fetch: bool = Field(default=False, description="是否实时采集")
    channels: list[str] = Field(default_factory=list, description="目标渠道")
    time_range: Optional[dict[str, str]] = Field(default=None, description="时间范围")
    risk_types: list[str] = Field(default_factory=list, description="风险类型")
    platforms: list[str] = Field(default_factory=list, description="目标平台")


class QueryResponse(BaseModel):
    """Response schema for query status."""
    query_id: str
    status: str
    progress: int = 0
    stage: Optional[str] = None
    message: Optional[str] = None
    result_stats: dict[str, int] = Field(default_factory=dict)
    failure_reason: Optional[str] = None
    updated_at: Optional[datetime] = None


class SSEvent(BaseModel):
    """Schema for SSE event payload."""
    type: str = Field(..., description="事件类型: stage|progress|content|complete|heartbeat|error")
    stage: Optional[str] = Field(default=None, description="阶段标识")
    content: Optional[str] = Field(default=None, description="内容")
    progress: Optional[int] = Field(default=None, ge=0, le=100, description="进度百分比")
    data: Optional[dict] = Field(default=None, description="附加数据")