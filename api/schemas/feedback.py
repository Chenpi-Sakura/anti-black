"""
Pydantic schemas for Feedback APIs
"""
from pydantic import BaseModel, Field
from typing import Optional


class FeedbackCreate(BaseModel):
    """Request schema for submitting feedback."""
    clue_id: str = Field(..., description="线索ID")
    feedback_type: str = Field(..., description="反馈类型: helpful|wrong_class|wrong_entity|normal|correction")
    correct_risk_label_level1: Optional[str] = Field(default=None, description="正确的一级风险标签")
    correct_risk_label_level2: Optional[str] = Field(default=None, description="正确的二级风险标签")
    correct_entities: list[dict] = Field(default_factory=list, description="正确的实体列表")
    comment: Optional[str] = Field(default=None, description="补充说明")
    operator: str = Field(default="", description="操作人")
    platinum_enrolled: bool = Field(default=False, description="是否加入铂金样本")
    sample_weight: int = Field(default=1, ge=1, description="样本权重")


class FeedbackResponse(BaseModel):
    """Response schema for feedback submission."""
    feedback_id: str
    message: str = "Feedback submitted successfully"
    platinum_enrolled: bool = False