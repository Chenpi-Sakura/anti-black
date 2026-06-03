"""
Core data models for AntiBlack system.
Defines all MongoDB collections and their schemas.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    """Entity types extracted from messages."""
    WECHAT = "WECHAT"
    PHONE = "PHONE"
    QQ = "QQ"
    URL = "URL"
    EMAIL = "EMAIL"
    SLANG = "SLANG"
    PRICE = "PRICE"
    PLATFORM = "PLATFORM"
    # === 黑灰产 M.O. & Toolchain 节点 (由 MOExtractor 写入) ===
    TOOL = "TOOL"           # 黑产工具: 接码平台 / 改机工具 / 群控系统
    TACTIC = "TACTIC"       # 战术动作: 养号 / 截流 / 爆粉 / 代实名
    TARGET = "TARGET"       # 攻击目标: 抖音直播间 / 本地生活评论区
    # === 黑灰产 Supply & Demand 节点 (由 MOExtractor 写入) ===
    RESOURCE = "RESOURCE"   # 黑产资源: 千粉号 / 实名号 / 蓝V号
    INTENT = "INTENT"       # 交易意图: 出 / 收 / 寻 / 代办
    SCENE = "SCENE"         # 应用场景: 无人直播 / 短剧推广


class RiskLevel(str, Enum):
    """Risk levels."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NORMAL = "NORMAL"


class SourceChannel(str, Enum):
    """Source channels for intelligence collection."""
    TELEGRAM = "telegram"
    X = "x"
    BAIDU_TIEBA = "baidu_tieba"
    DOUYIN = "douyin"
    REDNOTE = "rednote"
    SECONDHAND = "secondhand"
    ZHILIAN = "zhilian"
    DARKWEB = "darkweb"
    TECH_FORUM = "tech_forum"


class ClassificationSource(str, Enum):
    """Classification source indicators."""
    RULE = "rule"
    MODEL = "model"
    LLM = "llm"


class QueryStatus(str, Enum):
    """Query task status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class ExportStatus(str, Enum):
    """Export task status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PatrolStatus(str, Enum):
    """Background patrol status."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


class SystemStatus(str, Enum):
    """System ready status."""
    BOOTSTRAPPING = "BOOTSTRAPPING"
    READY = "READY"
    DEGRADED = "DEGRADED"


class SlangStatus(str, Enum):
    """Slang candidate status."""
    NEW = "NEW"
    OBSERVED = "OBSERVED"
    LIKELY = "LIKELY"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    STABLE = "STABLE"


class SeedWordStatus(str, Enum):
    """Seed word status."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    CANDIDATE = "candidate"


class RetrainStatus(str, Enum):
    """Retrain job status."""
    IDLE = "IDLE"
    TRIGGERED = "TRIGGERED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Entity:
    """Entity extracted from messages."""
    entity_id: str
    entity_type: EntityType
    raw_value: str
    normalized_value: Optional[str] = None
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    occurrence_count: int = 0
    source_channel: Optional[str] = None
    risk_labels: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value if isinstance(self.entity_type, EntityType) else self.entity_type,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "first_seen": self.first_seen.isoformat() if isinstance(self.first_seen, datetime) else self.first_seen,
            "last_seen": self.last_seen.isoformat() if isinstance(self.last_seen, datetime) else self.last_seen,
            "occurrence_count": self.occurrence_count,
            "source_channel": self.source_channel,
            "risk_labels": self.risk_labels,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Entity':
        entity_type = d.get('entity_type')
        if isinstance(entity_type, str):
            entity_type = EntityType(entity_type)
        return cls(
            entity_id=d['entity_id'],
            entity_type=entity_type,
            raw_value=d['raw_value'],
            normalized_value=d.get('normalized_value'),
            first_seen=d.get('first_seen', datetime.utcnow()),
            last_seen=d.get('last_seen', datetime.utcnow()),
            occurrence_count=d.get('occurrence_count', 0),
            source_channel=d.get('source_channel'),
            risk_labels=d.get('risk_labels', []),
            metadata=d.get('metadata', {})
        )


@dataclass
class MessageRef:
    """Reference from entity to original message."""
    ref_id: str
    entity_id: str
    message_id: str
    source: str
    context_snippet: str
    risk_label: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "entity_id": self.entity_id,
            "message_id": self.message_id,
            "source": self.source,
            "context_snippet": self.context_snippet,
            "risk_label": self.risk_label,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }


@dataclass
class SlangMapping:
    """Slang to standard term mapping."""
    mapping_id: str
    slang_raw: str
    meaning: str
    regex_pattern: Optional[str] = None
    source: str = "preset"
    verified: bool = False
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "slang_raw": self.slang_raw,
            "meaning": self.meaning,
            "regex_pattern": self.regex_pattern,
            "source": self.source,
            "verified": self.verified,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class SlangCandidate:
    """Candidate slang word for learning."""
    candidate_word: str
    contexts: List[str] = field(default_factory=list)
    occurrence_count: int = 0
    status: SlangStatus = SlangStatus.NEW
    inference_count: int = 0
    reject_until: Optional[datetime] = None
    regex_pattern: Optional[str] = None
    meaning: Optional[str] = None
    source_channel: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_word": self.candidate_word,
            "contexts": self.contexts,
            "occurrence_count": self.occurrence_count,
            "status": self.status.value if isinstance(self.status, SlangStatus) else self.status,
            "inference_count": self.inference_count,
            "reject_until": self.reject_until.isoformat() if self.reject_until else None,
            "regex_pattern": self.regex_pattern,
            "meaning": self.meaning,
            "source_channel": self.source_channel,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class QueryTask:
    """Query task for natural language queries."""
    query_id: str
    query_text: str
    status: QueryStatus = QueryStatus.PENDING
    parsed_intent: Dict[str, Any] = field(default_factory=dict)
    execution_plan: Dict[str, Any] = field(default_factory=dict)
    realtime_fetch: bool = False
    channels: List[str] = field(default_factory=list)
    time_range: Optional[Dict[str, str]] = None
    risk_types: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    progress: int = 0
    stage: Optional[str] = None
    message: Optional[str] = None
    result_stats: Dict[str, int] = field(default_factory=lambda: {
        "raw_message_count": 0,
        "cleaned_message_count": 0,
        "classified_message_count": 0,
        "clue_count": 0,
        "deep_analysis_count": 0
    })
    failure_reason: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "status": self.status.value if isinstance(self.status, QueryStatus) else self.status,
            "parsed_intent": self.parsed_intent,
            "execution_plan": self.execution_plan,
            "realtime_fetch": self.realtime_fetch,
            "channels": self.channels,
            "time_range": self.time_range,
            "risk_types": self.risk_types,
            "platforms": self.platforms,
            "constraints": self.constraints,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "result_stats": self.result_stats,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class Clue:
    """Processed intelligence clue."""
    clue_id: str
    message_id: str
    risk_label_level1: str
    risk_label_level2: str
    confidence: float
    classification_source: str
    raw_text: str
    cleaned_text: str
    classification_reason: Optional[str] = None
    source_channel: Optional[str] = None
    source_group_id: Optional[str] = None
    source_author_id: Optional[str] = None
    entity_list: List[Dict[str, Any]] = field(default_factory=list)
    slang_mappings: List[Dict[str, str]] = field(default_factory=list)
    graph_relations: List[Dict[str, Any]] = field(default_factory=list)
    query_id: Optional[str] = None
    platform: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clue_id": self.clue_id,
            "message_id": self.message_id,
            "risk_label_level1": self.risk_label_level1,
            "risk_label_level2": self.risk_label_level2,
            "confidence": self.confidence,
            "classification_source": self.classification_source,
            "classification_reason": self.classification_reason,
            "source_channel": self.source_channel,
            "source_group_id": self.source_group_id,
            "source_author_id": self.source_author_id,
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "entity_list": self.entity_list,
            "slang_mappings": self.slang_mappings,
            "graph_relations": self.graph_relations,
            "query_id": self.query_id,
            "platform": self.platform,
            "published_at": self.published_at.isoformat() if isinstance(self.published_at, datetime) else self.published_at,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }


@dataclass
class Feedback:
    """User feedback for corrections."""
    feedback_id: str
    clue_id: str
    feedback_type: str
    correct_risk_label_level1: Optional[str] = None
    correct_risk_label_level2: Optional[str] = None
    correct_entities: List[Dict[str, str]] = field(default_factory=list)
    comment: Optional[str] = None
    operator: str = ""
    platinum_enrolled: bool = False
    sample_weight: int = 1
    model_update_status: str = "IDLE"
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "clue_id": self.clue_id,
            "feedback_type": self.feedback_type,
            "correct_risk_label_level1": self.correct_risk_label_level1,
            "correct_risk_label_level2": self.correct_risk_label_level2,
            "correct_entities": self.correct_entities,
            "comment": self.comment,
            "operator": self.operator,
            "platinum_enrolled": self.platinum_enrolled,
            "sample_weight": self.sample_weight,
            "model_update_status": self.model_update_status,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }


@dataclass
class SeedWord:
    """Seed word for collection."""
    word: str
    status: SeedWordStatus = SeedWordStatus.ACTIVE
    source: str = "preset"
    weekly_hit_count: int = 0
    effective_clue_ratio: float = 0.0
    last_promoted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "status": self.status.value if isinstance(self.status, SeedWordStatus) else self.status,
            "source": self.source,
            "weekly_hit_count": self.weekly_hit_count,
            "effective_clue_ratio": self.effective_clue_ratio,
            "last_promoted_at": self.last_promoted_at.isoformat() if self.last_promoted_at else None,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class Proposal:
    """Rule or classification proposal."""
    proposal_id: str
    proposal_type: str
    title: str
    detail: str
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    operator: Optional[str] = None
    comment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "operator": self.operator,
            "comment": self.comment
        }


@dataclass
class ExportTask:
    """Export task for data export."""
    export_id: str
    query_id: Optional[str] = None
    filters: Dict[str, Any] = field(default_factory=dict)
    export_format: str = "json"
    include_graph_relations: bool = False
    operator: str = ""
    status: ExportStatus = ExportStatus.PENDING
    download_url: Optional[str] = None
    expire_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "export_id": self.export_id,
            "query_id": self.query_id,
            "filters": self.filters,
            "export_format": self.export_format,
            "include_graph_relations": self.include_graph_relations,
            "operator": self.operator,
            "status": self.status.value if isinstance(self.status, ExportStatus) else self.status,
            "download_url": self.download_url,
            "expire_at": self.expire_at.isoformat() if self.expire_at else None,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }


@dataclass
class Channel:
    """Channel configuration."""
    platform: str
    platform_name: str
    category: str
    status: str = "unconfigured"
    enabled: bool = False
    config: Dict[str, Any] = field(default_factory=dict)
    configured_at: Optional[datetime] = None
    messages_today: int = 0
    last_polling_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "platform_name": self.platform_name,
            "category": self.category,
            "status": self.status,
            "enabled": self.enabled,
            "config": self.config,
            "configured_at": self.configured_at.isoformat() if self.configured_at else None,
            "messages_today": self.messages_today,
            "last_polling_at": self.last_polling_at.isoformat() if self.last_polling_at else None,
            "error_message": self.error_message
        }


@dataclass
class Metrics:
    """System metrics."""
    date: str
    token_usage_today: int = 0
    token_remaining_percent: float = 1.0
    collection_success_rate: float = 1.0
    total_entities: int = 0
    total_relations: int = 0
    messages_processed_today: int = 0
    background_patrol_status: PatrolStatus = PatrolStatus.IDLE
    last_patrol_at: Optional[datetime] = None
    classification_distribution: List[Dict[str, Any]] = field(default_factory=list)
    channel_status: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "token_usage_today": self.token_usage_today,
            "token_remaining_percent": self.token_remaining_percent,
            "collection_success_rate": self.collection_success_rate,
            "total_entities": self.total_entities,
            "total_relations": self.total_relations,
            "messages_processed_today": self.messages_processed_today,
            "background_patrol_status": self.background_patrol_status.value if isinstance(self.background_patrol_status, PatrolStatus) else self.background_patrol_status,
            "last_patrol_at": self.last_patrol_at.isoformat() if self.last_patrol_at else None,
            "classification_distribution": self.classification_distribution,
            "channel_status": self.channel_status,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class AutoEvolution:
    """Auto evolution status tracking."""
    silver_sample_count: int = 0
    platinum_sample_count: int = 0
    error_book_count: int = 0
    current_model_version: str = "v0.0.0"
    retrain_status: RetrainStatus = RetrainStatus.IDLE
    retrain_trigger_threshold: int = 2000
    last_retrain_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "silver_sample_count": self.silver_sample_count,
            "platinum_sample_count": self.platinum_sample_count,
            "error_book_count": self.error_book_count,
            "current_model_version": self.current_model_version,
            "retrain_status": self.retrain_status.value if isinstance(self.retrain_status, RetrainStatus) else self.retrain_status,
            "retrain_trigger_threshold": self.retrain_trigger_threshold,
            "last_retrain_at": self.last_retrain_at.isoformat() if self.last_retrain_at else None,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }


@dataclass
class Conversation:
    """Conversation session for query history."""
    conversation_id: str
    title: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "title": self.title,
            "messages": self.messages,
            "timeline": self.timeline,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }
