"""
Pydantic schemas for Clue APIs
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ClueQueryParams(BaseModel):
    """Query parameters for clues list."""
    query_id: Optional[str] = Field(default=None, description="查询ID")
    risk_label_level1: Optional[str] = Field(default=None, description="一级风险标签")
    risk_label_level2: Optional[str] = Field(default=None, description="二级风险标签")
    source_channel: Optional[str] = Field(default=None, description="来源渠道")
    min_confidence: float = Field(default=0, ge=0, le=1, description="最低置信度")
    start_time: Optional[str] = Field(default=None, description="开始时间")
    end_time: Optional[str] = Field(default=None, description="结束时间")
    page_no: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=1, le=100, description="每页条数")
    sort_by: str = Field(default="published_at", description="排序字段")
    sort_order: int = Field(default=-1, description="排序方向: -1降序, 1升序")


class ClueResponse(BaseModel):
    """Response schema for a single clue."""
    clue_id: str
    message_id: str
    risk_label_level1: str
    risk_label_level2: str
    confidence: float
    classification_source: str
    raw_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    classification_reason: Optional[str] = None
    source_channel: Optional[str] = None
    source_group_id: Optional[str] = None
    source_author_id: Optional[str] = None
    entity_list: list[dict] = Field(default_factory=list)
    slang_mappings: list[dict] = Field(default_factory=list)
    graph_relations: list[dict] = Field(default_factory=list)
    query_id: Optional[str] = None
    platform: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ClueListResponse(BaseModel):
    """Response schema for clues list with pagination."""
    page_no: int
    page_size: int
    total: int
    items: list[ClueResponse]