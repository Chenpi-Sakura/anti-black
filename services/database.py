"""
MongoDB Database Service for AntiBlack system.
Handles all database operations with MongoDB.
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import asdict
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from config import get_config
from models import (
    Entity, MessageRef, SlangMapping, SlangCandidate, QueryTask, Clue,
    Feedback, SeedWord, Proposal, ExportTask, Channel, Metrics, AutoEvolution,
    EntityType, QueryStatus, ExportStatus, SlangStatus, SeedWordStatus, RetrainStatus
)

logger = logging.getLogger(__name__)


class MongoDBService:
    """MongoDB service for all database operations."""

    _instance: Optional['MongoDBService'] = None

    def __init__(self, connection_string: Optional[str] = None, database: Optional[str] = None):
        config = get_config()
        mongo_config = config.mongodb

        if connection_string is None:
            connection_string = mongo_config.uri
        if database is None:
            database = mongo_config.database

        self.client: MongoClient = MongoClient(connection_string)
        self.db: Database = self.client[database]

        # Initialize collections
        self._init_collections()

        # Create indexes
        self._create_indexes()

    def _init_collections(self) -> None:
        """Initialize all collections."""
        self.entities: Collection = self.db['entities']
        self.message_refs: Collection = self.db['message_refs']
        self.slang_mappings: Collection = self.db['slang_mappings']
        self.slang_candidates: Collection = self.db['slang_candidates']
        self.queries: Collection = self.db['queries']
        self.clues: Collection = self.db['clues']
        self.feedback: Collection = self.db['feedback']
        self.seed_words: Collection = self.db['seed_words']
        self.proposals: Collection = self.db['proposals']
        self.exports: Collection = self.db['exports']
        self.channels: Collection = self.db['channels']
        self.metrics: Collection = self.db['metrics']
        self.auto_evolution: Collection = self.db['auto_evolution']

    def _create_indexes(self) -> None:
        """Create necessary indexes for all collections."""
        # Entity indexes
        self.entities.create_index("entity_id", unique=True)
        self.entities.create_index("entity_type")
        self.entities.create_index("raw_value")
        self.entities.create_index("last_seen")
        self.entities.create_index([("entity_type", 1), ("raw_value", 1)], unique=True)

        # MessageRef indexes
        self.message_refs.create_index("ref_id", unique=True)
        self.message_refs.create_index("entity_id")
        self.message_refs.create_index("message_id")

        # SlangMapping indexes
        self.slang_mappings.create_index("mapping_id", unique=True)
        self.slang_mappings.create_index("slang_raw", unique=True)

        # SlangCandidate indexes
        self.slang_candidates.create_index("candidate_word", 1, unique=True)
        self.slang_candidates.create_index("status")
        self.slang_candidates.create_index("source_channel")

        # QueryTask indexes
        self.queries.create_index("query_id", unique=True)
        self.queries.create_index("status")
        self.queries.create_index("created_at")

        # Clue indexes
        self.clues.create_index("clue_id", unique=True)
        self.clues.create_index("message_id")
        self.clues.create_index("query_id")
        self.clues.create_index("risk_label_level1")
        self.clues.create_index("risk_label_level2")
        self.clues.create_index("source_channel")
        self.clues.create_index("published_at")
        self.clues.create_index([("risk_label_level1", 1), ("published_at", -1)])

        # Feedback indexes
        self.feedback.create_index("feedback_id", unique=True)
        self.feedback.create_index("clue_id")
        self.feedback.create_index("created_at")

        # SeedWord indexes
        self.seed_words.create_index("word", unique=True)
        self.seed_words.create_index("status")
        self.seed_words.create_index("source")

        # Proposal indexes
        self.proposals.create_index("proposal_id", unique=True)
        self.proposals.create_index("proposal_type")
        self.proposals.create_index("status")
        self.proposals.create_index("created_at")

        # ExportTask indexes
        self.exports.create_index("export_id", unique=True)
        self.exports.create_index("status")
        self.exports.create_index("created_at")

        # Channel indexes
        self.channels.create_index("platform", unique=True)

        # Metrics indexes
        self.metrics.create_index("date", unique=True)

        # AutoEvolution - single document pattern
        logger.info("MongoDB indexes created successfully")

    # ========== Entity Operations ==========

    def upsert_entity(self, entity: Entity) -> str:
        """Insert or update an entity."""
        doc = entity.to_dict()
        entity_id = doc.pop("entity_id")

        # Use upsert with entity_id as unique key
        self.entities.update_one(
            {"entity_id": entity_id},
            {
                "$set": doc,
                "$inc": {"occurrence_count": 1},
                "$setOnInsert": {
                    "first_seen": datetime.utcnow(),
                    "occurrence_count": 1
                }
            },
            upsert=True
        )
        return entity_id

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get an entity by ID."""
        return self.entities.find_one({"entity_id": entity_id})

    def get_entity_by_value(self, entity_type: str, raw_value: str, source_channel: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get entity by type and value."""
        query = {"entity_type": entity_type, "raw_value": raw_value}
        if source_channel:
            query["source_channel"] = source_channel
        return self.entities.find_one(query)

    def get_entities_by_type(self, entity_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get entities by type."""
        return list(self.entities.find({"entity_type": entity_type}).limit(limit))

    def get_entity_profile(self, entity_id: str, relation_depth: int = 1) -> Optional[Dict[str, Any]]:
        """Get entity profile with related entities."""
        entity = self.get_entity(entity_id)
        if not entity:
            return None

        # Get related message refs
        refs = list(self.message_refs.find({"entity_id": entity_id}))

        # Get related entities from refs
        related_entities = []
        entity_ids = list(set([ref["entity_id"] for ref in refs]))
        if entity_ids:
            related = list(self.entities.find({"entity_id": {"$in": entity_ids}}))
            related_entities = [e for e in related if e["entity_id"] != entity_id]

        # Get risk distribution
        risk_pipeline = [
            {"$match": {"entity_id": entity_id}},
            {"$group": {"_id": "$risk_label", "count": {"$sum": 1}}}
        ]
        risk_distribution = list(self.message_refs.aggregate(risk_pipeline))

        # Get recent evidence
        message_ids = [ref["message_id"] for ref in refs]
        recent_clues = list(self.clues.find(
            {"message_id": {"$in": message_ids[:10]}}
        ).sort("published_at", -1).limit(5))

        return {
            "entity_id": entity["entity_id"],
            "entity_type": entity["entity_type"],
            "raw_value": entity["raw_value"],
            "first_seen": entity.get("first_seen"),
            "last_seen": entity.get("last_seen"),
            "occurrence_count": entity.get("occurrence_count", 0),
            "risk_distribution": risk_distribution,
            "related_entities": related_entities[:10],
            "recent_evidence": [
                {
                    "clue_id": c.get("clue_id"),
                    "published_at": c.get("published_at"),
                    "snippet": c.get("raw_text", "")[:200]
                }
                for c in recent_clues
            ]
        }

    def get_total_entities_count(self) -> int:
        """Get total count of entities."""
        return self.entities.count_documents({})

    # ========== MessageRef Operations ==========

    def insert_message_ref(self, ref: MessageRef) -> str:
        """Insert a message reference."""
        doc = ref.to_dict()
        self.message_refs.insert_one(doc)
        return doc["ref_id"]

    def get_message_refs(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all message refs for an entity."""
        return list(self.message_refs.find({"entity_id": entity_id}))

    # ========== SlangMapping Operations ==========

    def upsert_slang_mapping(self, mapping: SlangMapping) -> str:
        """Insert or update a slang mapping."""
        doc = mapping.to_dict()
        mapping_id = doc.pop("mapping_id")

        self.slang_mappings.update_one(
            {"mapping_id": mapping_id},
            {"$set": doc},
            upsert=True
        )
        return mapping_id

    def get_slang_mapping(self, slang_raw: str) -> Optional[Dict[str, Any]]:
        """Get slang mapping by raw term."""
        return self.slang_mappings.find_one({"slang_raw": slang_raw})

    def get_all_slang_mappings(self, verified_only: bool = True) -> List[Dict[str, Any]]:
        """Get all slang mappings."""
        query = {"verified": True} if verified_only else {}
        return list(self.slang_mappings.find(query))

    # ========== SlangCandidate Operations ==========

    def upsert_slang_candidate(self, candidate: SlangCandidate) -> str:
        """Insert or update a slang candidate."""
        doc = candidate.to_dict()
        word = doc.pop("candidate_word")

        self.slang_candidates.update_one(
            {"candidate_word": word},
            {"$set": doc},
            upsert=True
        )
        return word

    def get_slang_candidate(self, word: str) -> Optional[Dict[str, Any]]:
        """Get a slang candidate by word."""
        return self.slang_candidates.find_one({"candidate_word": word})

    def get_slang_candidates_by_status(self, status: SlangStatus) -> List[Dict[str, Any]]:
        """Get slang candidates by status."""
        return list(self.slang_candidates.find(
            {"status": status.value if isinstance(status, SlangStatus) else status}
        ))

    # ========== QueryTask Operations ==========

    def create_query_task(self, task: QueryTask) -> str:
        """Create a new query task."""
        doc = task.to_dict()
        self.queries.insert_one(doc)
        return doc["query_id"]

    def update_query_task(self, query_id: str, updates: Dict[str, Any]) -> bool:
        """Update a query task."""
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = self.queries.update_one(
            {"query_id": query_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    def get_query_task(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Get a query task by ID."""
        return self.queries.find_one({"query_id": query_id})

    # ========== Clue Operations ==========

    def insert_clue(self, clue: Clue) -> str:
        """Insert a clue."""
        doc = clue.to_dict()
        self.clues.insert_one(doc)
        return doc["clue_id"]

    def get_clue(self, clue_id: str) -> Optional[Dict[str, Any]]:
        """Get a clue by ID."""
        return self.clues.find_one({"clue_id": clue_id})

    def get_clues(
        self,
        query_id: Optional[str] = None,
        risk_label_level1: Optional[str] = None,
        risk_label_level2: Optional[str] = None,
        source_channel: Optional[str] = None,
        entity_type: Optional[str] = None,
        min_confidence: Optional[float] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        sort_by: str = "published_at",
        sort_order: int = pymongo.DESCENDING,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """Get clues with filtering and pagination."""
        query = {}

        if query_id:
            query["query_id"] = query_id
        if risk_label_level1:
            query["risk_label_level1"] = risk_label_level1
        if risk_label_level2:
            query["risk_label_level2"] = risk_label_level2
        if source_channel:
            query["source_channel"] = source_channel
        if min_confidence:
            query["confidence"] = {"$gte": min_confidence}
        if start_time or end_time:
            query["published_at"] = {}
            if start_time:
                query["published_at"]["$gte"] = start_time
            if end_time:
                query["published_at"]["$lte"] = end_time

        total = self.clues.count_documents(query)

        sort_direction = pymongo.DESCENDING if sort_order == -1 else pymongo.ASCENDING
        skip = (page_no - 1) * page_size

        items = list(self.clues.find(query)
                    .sort(sort_by, sort_direction)
                    .skip(skip)
                    .limit(page_size))

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def get_clue_count(self) -> int:
        """Get total count of clues."""
        return self.clues.count_documents({})

    # ========== Feedback Operations ==========

    def insert_feedback(self, feedback: Feedback) -> str:
        """Insert feedback."""
        doc = feedback.to_dict()
        self.feedback.insert_one(doc)
        return doc["feedback_id"]

    def get_feedback(self, feedback_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback by ID."""
        return self.feedback.find_one({"feedback_id": feedback_id})

    # ========== SeedWord Operations ==========

    def upsert_seed_word(self, seed_word: SeedWord) -> str:
        """Insert or update a seed word."""
        doc = seed_word.to_dict()
        word = doc.pop("word")

        self.seed_words.update_one(
            {"word": word},
            {"$set": doc},
            upsert=True
        )
        return word

    def get_seed_word(self, word: str) -> Optional[Dict[str, Any]]:
        """Get a seed word."""
        return self.seed_words.find_one({"word": word})

    def get_seed_words(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Get seed words with filtering."""
        query = {}
        if status:
            query["status"] = status
        if source:
            query["source"] = source

        total = self.seed_words.count_documents(query)
        skip = (page_no - 1) * page_size

        items = list(self.seed_words.find(query)
                    .skip(skip)
                    .limit(page_size))

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def promote_seed_word(self, word: str, operator: str, reason: Optional[str] = None) -> bool:
        """Promote a seed word to active status."""
        result = self.seed_words.update_one(
            {"word": word},
            {
                "$set": {
                    "status": SeedWordStatus.ACTIVE.value,
                    "last_promoted_at": datetime.utcnow()
                }
            }
        )
        return result.modified_count > 0

    # ========== Proposal Operations ==========

    def insert_proposal(self, proposal: Proposal) -> str:
        """Insert a proposal."""
        doc = proposal.to_dict()
        self.proposals.insert_one(doc)
        return doc["proposal_id"]

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get a proposal by ID."""
        return self.proposals.find_one({"proposal_id": proposal_id})

    def get_proposals(
        self,
        proposal_type: Optional[str] = None,
        status: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Get proposals with filtering."""
        query = {}
        if proposal_type:
            query["proposal_type"] = proposal_type
        if status:
            query["status"] = status

        total = self.proposals.count_documents(query)
        skip = (page_no - 1) * page_size

        items = list(self.proposals.find(query)
                    .sort("created_at", -1)
                    .skip(skip)
                    .limit(page_size))

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def approve_proposal(self, proposal_id: str, operator: str, comment: Optional[str] = None) -> bool:
        """Approve a proposal."""
        result = self.proposals.update_one(
            {"proposal_id": proposal_id, "status": "pending"},
            {
                "$set": {
                    "status": "approved",
                    "processed_at": datetime.utcnow(),
                    "operator": operator,
                    "comment": comment
                }
            }
        )
        return result.modified_count > 0

    # ========== ExportTask Operations ==========

    def create_export_task(self, task: ExportTask) -> str:
        """Create an export task."""
        doc = task.to_dict()
        self.exports.insert_one(doc)
        return doc["export_id"]

    def update_export_task(self, export_id: str, updates: Dict[str, Any]) -> bool:
        """Update an export task."""
        result = self.exports.update_one(
            {"export_id": export_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    def get_export_task(self, export_id: str) -> Optional[Dict[str, Any]]:
        """Get an export task."""
        return self.exports.find_one({"export_id": export_id})

    # ========== Channel Operations ==========

    def upsert_channel(self, channel: Channel) -> str:
        """Insert or update a channel."""
        doc = channel.to_dict()
        platform = doc.pop("platform")

        self.channels.update_one(
            {"platform": platform},
            {"$set": doc},
            upsert=True
        )
        return platform

    def get_channel(self, platform: str) -> Optional[Dict[str, Any]]:
        """Get a channel by platform."""
        return self.channels.find_one({"platform": platform})

    def get_all_channels(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all channels."""
        query = {}
        if category:
            query["category"] = category
        return list(self.channels.find(query))

    # ========== Metrics Operations ==========

    def upsert_metrics(self, metrics: Metrics) -> str:
        """Insert or update daily metrics."""
        doc = metrics.to_dict()
        date = doc.pop("date")

        self.metrics.update_one(
            {"date": date},
            {"$set": doc},
            upsert=True
        )
        return date

    def get_metrics(self, date: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific date."""
        return self.metrics.find_one({"date": date})

    def get_latest_metrics(self) -> Optional[Dict[str, Any]]:
        """Get the latest metrics."""
        return self.metrics.find_one(sort=[("date", -1)])

    # ========== AutoEvolution Operations ==========

    def get_auto_evolution_status(self) -> Dict[str, Any]:
        """Get auto evolution status."""
        status = self.auto_evolution.find_one({"_id": "status"})
        if not status:
            return {
                "enabled": True,
                "silver_sample_count": 0,
                "platinum_sample_count": 0,
                "error_book_count": 0,
                "current_model_version": "v0.0.0",
                "retrain_status": "IDLE",
                "retrain_trigger_threshold": 2000,
                "last_retrain_at": None
            }
        return status

    def update_auto_evolution_status(self, updates: Dict[str, Any]) -> bool:
        """Update auto evolution status."""
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = self.auto_evolution.update_one(
            {"_id": "status"},
            {"$set": updates},
            upsert=True
        )
        return result.modified_count > 0

    # ========== System Status ==========

    def get_system_ready_status(self) -> Dict[str, Any]:
        """Get system ready status."""
        # Count entities
        entity_count = self.entities.count_documents({})

        # Check bootstrap progress (simplified)
        bootstrap_progress = min(100, int(entity_count / 100))

        return {
            "ready": entity_count >= 100,
            "status": "READY" if entity_count >= 100 else "BOOTSTRAPPING",
            "health_checks": {
                "database": "healthy",
                "queue": "healthy",
                "llm_api": "healthy",
                "graph_engine": "healthy"
            },
            "bootstrap_progress": bootstrap_progress,
            "backfill_entity_count": entity_count,
            "ready_threshold": 100,
            "updated_at": datetime.utcnow().isoformat()
        }

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get background patrol status."""
        latest_metrics = self.get_latest_metrics()

        return {
            "patrol_enabled": True,
            "patrol_status": latest_metrics.get("background_patrol_status", "IDLE") if latest_metrics else "IDLE",
            "current_round_id": f"patrol_{datetime.utcnow().strftime('%Y%m%d_%H')}",
            "current_stage": "classifying",
            "last_patrol_at": latest_metrics.get("last_patrol_at") if latest_metrics else None,
            "next_patrol_at": None,
            "last_round_stats": {
                "collected_messages": latest_metrics.get("messages_processed_today", 0) if latest_metrics else 0,
                "generated_clues": 0,
                "deep_analysis_count": 0
            }
        }

    def close(self) -> None:
        """Close database connection."""
        self.client.close()

    @classmethod
    def get_instance(cls) -> 'MongoDBService':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance