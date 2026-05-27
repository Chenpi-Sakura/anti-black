"""
PostgreSQL Database Service for AntiBlack system.
Handles all database operations with PostgreSQL using psycopg2.
Uses 'antiblack' schema for AntiBlack tables.
"""
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, Json

from config import get_config
from models import (
    Entity, MessageRef, SlangMapping, SlangCandidate, QueryTask, Clue,
    Feedback, SeedWord, Proposal, ExportTask, Channel, Metrics, AutoEvolution,
    EntityType, QueryStatus, ExportStatus, SlangStatus, SeedWordStatus, RetrainStatus,
    Conversation
)

logger = logging.getLogger(__name__)


class PostgreSQLService:
    """PostgreSQL service for all database operations using antiblack schema."""

    _instance: Optional['PostgreSQLService'] = None

    def __init__(self):
        config = get_config()
        pg_config = config.postgresql

        self.host = pg_config.host
        self.port = pg_config.port
        self.user = pg_config.user
        self.password = pg_config.password
        self.database = pg_config.database
        self.schema = 'antiblack'

        self._conn: Optional[psycopg2.extensions.connection] = None
        self._connect()
        self._init_schema()
        self._create_tables()
        self._create_indexes()

    def _connect(self) -> None:
        """Establish database connection."""
        self._conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            cursor_factory=RealDictCursor
        )
        self._conn.autocommit = True
        logger.info(f"Connected to PostgreSQL {self.host}:{self.port}/{self.database}")

    def _get_cursor(self):
        """Get a new cursor."""
        return self._conn.cursor()

    def _init_schema(self) -> None:
        """Create antiblack schema if not exists."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(self.schema)))
            logger.info(f"Schema '{self.schema}' ready")

    def _create_tables(self) -> None:
        """Create all tables in antiblack schema."""
        schema = self.schema

        table_defs = [
            # entities table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.entities (
                entity_id VARCHAR(255) PRIMARY KEY,
                entity_type VARCHAR(50) NOT NULL,
                raw_value TEXT NOT NULL,
                normalized_value TEXT,
                first_seen TIMESTAMP DEFAULT NOW(),
                last_seen TIMESTAMP DEFAULT NOW(),
                occurrence_count INTEGER DEFAULT 0,
                source_channel VARCHAR(50),
                risk_labels JSONB DEFAULT '[]',
                metadata JSONB DEFAULT '{{}}',
                UNIQUE(entity_type, raw_value)
            )
            """,

            # message_refs table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.message_refs (
                ref_id VARCHAR(255) PRIMARY KEY,
                entity_id VARCHAR(255) NOT NULL,
                message_id VARCHAR(255) NOT NULL,
                source VARCHAR(50),
                context_snippet TEXT,
                risk_label VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # slang_mappings table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.slang_mappings (
                mapping_id VARCHAR(255) PRIMARY KEY,
                slang_raw VARCHAR(255) UNIQUE NOT NULL,
                meaning TEXT NOT NULL,
                regex_pattern TEXT,
                source VARCHAR(50) DEFAULT 'preset',
                verified BOOLEAN DEFAULT FALSE,
                confidence REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # slang_candidates table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.slang_candidates (
                candidate_word VARCHAR(255) PRIMARY KEY,
                contexts JSONB DEFAULT '[]',
                occurrence_count INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'NEW',
                inference_count INTEGER DEFAULT 0,
                reject_until TIMESTAMP,
                regex_pattern TEXT,
                meaning TEXT,
                source_channel VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # queries table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.queries (
                query_id VARCHAR(255) PRIMARY KEY,
                query_text TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'PENDING',
                parsed_intent JSONB DEFAULT '{{}}',
                execution_plan JSONB DEFAULT '{{}}',
                realtime_fetch BOOLEAN DEFAULT FALSE,
                channels JSONB DEFAULT '[]',
                time_range JSONB,
                risk_types JSONB DEFAULT '[]',
                platforms JSONB DEFAULT '[]',
                constraints JSONB DEFAULT '{{}}',
                progress INTEGER DEFAULT 0,
                stage VARCHAR(50),
                message TEXT,
                result_stats JSONB DEFAULT '{{"raw_message_count": 0, "cleaned_message_count": 0, "classified_message_count": 0, "clue_count": 0, "deep_analysis_count": 0}}',
                failure_reason TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # clues table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.clues (
                clue_id VARCHAR(255) PRIMARY KEY,
                message_id VARCHAR(255) NOT NULL,
                risk_label_level1 VARCHAR(100) NOT NULL,
                risk_label_level2 VARCHAR(100) NOT NULL,
                confidence REAL NOT NULL,
                classification_source VARCHAR(50) NOT NULL,
                raw_text TEXT,
                cleaned_text TEXT,
                classification_reason TEXT,
                source_channel VARCHAR(50),
                source_group_id VARCHAR(255),
                source_author_id VARCHAR(255),
                entity_list JSONB DEFAULT '[]',
                slang_mappings JSONB DEFAULT '[]',
                graph_relations JSONB DEFAULT '[]',
                query_id VARCHAR(255),
                platform VARCHAR(50),
                published_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # feedback table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.feedback (
                feedback_id VARCHAR(255) PRIMARY KEY,
                clue_id VARCHAR(255) NOT NULL,
                feedback_type VARCHAR(50) NOT NULL,
                correct_risk_label_level1 VARCHAR(100),
                correct_risk_label_level2 VARCHAR(100),
                correct_entities JSONB DEFAULT '[]',
                comment TEXT,
                operator VARCHAR(100) DEFAULT '',
                platinum_enrolled BOOLEAN DEFAULT FALSE,
                sample_weight INTEGER DEFAULT 1,
                model_update_status VARCHAR(50) DEFAULT 'IDLE',
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # seed_words table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.seed_words (
                word VARCHAR(255) PRIMARY KEY,
                status VARCHAR(50) DEFAULT 'active',
                source VARCHAR(50) DEFAULT 'preset',
                weekly_hit_count INTEGER DEFAULT 0,
                effective_clue_ratio REAL DEFAULT 0.0,
                last_promoted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # proposals table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.proposals (
                proposal_id VARCHAR(255) PRIMARY KEY,
                proposal_type VARCHAR(50) NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                processed_at TIMESTAMP,
                operator VARCHAR(100),
                comment TEXT
            )
            """,

            # exports table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.exports (
                export_id VARCHAR(255) PRIMARY KEY,
                query_id VARCHAR(255),
                filters JSONB DEFAULT '{{}}',
                export_format VARCHAR(20) DEFAULT 'json',
                include_graph_relations BOOLEAN DEFAULT FALSE,
                operator VARCHAR(100) DEFAULT '',
                status VARCHAR(50) DEFAULT 'PENDING',
                download_url TEXT,
                expire_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # channels table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.channels (
                platform VARCHAR(50) PRIMARY KEY,
                platform_name VARCHAR(100) NOT NULL,
                category VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'unconfigured',
                enabled BOOLEAN DEFAULT FALSE,
                config JSONB DEFAULT '{{}}',
                configured_at TIMESTAMP,
                messages_today INTEGER DEFAULT 0,
                last_polling_at TIMESTAMP,
                error_message TEXT
            )
            """,

            # metrics table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.metrics (
                date VARCHAR(20) PRIMARY KEY,
                token_usage_today INTEGER DEFAULT 0,
                token_remaining_percent REAL DEFAULT 1.0,
                collection_success_rate REAL DEFAULT 1.0,
                total_entities INTEGER DEFAULT 0,
                total_relations INTEGER DEFAULT 0,
                messages_processed_today INTEGER DEFAULT 0,
                background_patrol_status VARCHAR(50) DEFAULT 'IDLE',
                last_patrol_at TIMESTAMP,
                classification_distribution JSONB DEFAULT '[]',
                channel_status JSONB DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # auto_evolution table (single-row pattern)
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.auto_evolution (
                id VARCHAR(50) PRIMARY KEY DEFAULT 'status',
                silver_sample_count INTEGER DEFAULT 0,
                platinum_sample_count INTEGER DEFAULT 0,
                error_book_count INTEGER DEFAULT 0,
                current_model_version VARCHAR(50) DEFAULT 'v0.0.0',
                retrain_status VARCHAR(50) DEFAULT 'IDLE',
                retrain_trigger_threshold INTEGER DEFAULT 2000,
                last_retrain_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,

            # conversations table
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.conversations (
                conversation_id VARCHAR(255) PRIMARY KEY,
                title VARCHAR(255),
                messages JSONB DEFAULT '[]',
                timeline JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """
        ]

        with self._get_cursor() as cur:
            for table_def in table_defs:
                cur.execute(table_def)

        logger.info(f"Created {len(table_defs)} tables in schema '{schema}'")

    def _create_indexes(self) -> None:
        """Create necessary indexes."""
        schema = self.schema

        indexes = [
            # Entity indexes
            (f"CREATE INDEX IF NOT EXISTS idx_entities_entity_type ON {schema}.entities(entity_type)",),
            (f"CREATE INDEX IF NOT EXISTS idx_entities_raw_value ON {schema}.entities(raw_value)",),
            (f"CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON {schema}.entities(last_seen)",),
            (f"CREATE INDEX IF NOT EXISTS idx_entities_entity_type_raw ON {schema}.entities(entity_type, raw_value)",),

            # MessageRef indexes
            (f"CREATE INDEX IF NOT EXISTS idx_message_refs_entity_id ON {schema}.message_refs(entity_id)",),
            (f"CREATE INDEX IF NOT EXISTS idx_message_refs_message_id ON {schema}.message_refs(message_id)",),

            # SlangCandidate indexes
            (f"CREATE INDEX IF NOT EXISTS idx_slang_candidates_status ON {schema}.slang_candidates(status)",),
            (f"CREATE INDEX IF NOT EXISTS idx_slang_candidates_source_channel ON {schema}.slang_candidates(source_channel)",),

            # QueryTask indexes
            (f"CREATE INDEX IF NOT EXISTS idx_queries_status ON {schema}.queries(status)",),
            (f"CREATE INDEX IF NOT EXISTS idx_queries_created_at ON {schema}.queries(created_at)",),

            # Clue indexes
            (f"CREATE INDEX IF NOT EXISTS idx_clues_message_id ON {schema}.clues(message_id)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_query_id ON {schema}.clues(query_id)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_risk_level1 ON {schema}.clues(risk_label_level1)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_risk_level2 ON {schema}.clues(risk_label_level2)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_source_channel ON {schema}.clues(source_channel)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_published_at ON {schema}.clues(published_at)",),
            (f"CREATE INDEX IF NOT EXISTS idx_clues_risk_published ON {schema}.clues(risk_label_level1, published_at DESC)",),

            # Feedback indexes
            (f"CREATE INDEX IF NOT EXISTS idx_feedback_clue_id ON {schema}.feedback(clue_id)",),
            (f"CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON {schema}.feedback(created_at)",),

            # SeedWord indexes
            (f"CREATE INDEX IF NOT EXISTS idx_seed_words_status ON {schema}.seed_words(status)",),
            (f"CREATE INDEX IF NOT EXISTS idx_seed_words_source ON {schema}.seed_words(source)",),

            # Proposal indexes
            (f"CREATE INDEX IF NOT EXISTS idx_proposals_proposal_type ON {schema}.proposals(proposal_type)",),
            (f"CREATE INDEX IF NOT EXISTS idx_proposals_status ON {schema}.proposals(status)",),
            (f"CREATE INDEX IF NOT EXISTS idx_proposals_created_at ON {schema}.proposals(created_at)",),

            # ExportTask indexes
            (f"CREATE INDEX IF NOT EXISTS idx_exports_status ON {schema}.exports(status)",),
            (f"CREATE INDEX IF NOT EXISTS idx_exports_created_at ON {schema}.exports(created_at)",),

            # Conversation indexes
            (f"CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON {schema}.conversations(created_at DESC)",),
        ]

        with self._get_cursor() as cur:
            for idx_def in indexes:
                cur.execute(idx_def[0])

        logger.info(f"Created {len(indexes)} indexes in schema '{schema}'")

    # ========== Entity Operations ==========

    def upsert_entity(self, entity: Entity) -> str:
        """Insert or update an entity."""
        doc = entity.to_dict()
        entity_id = doc.pop("entity_id")

        # Convert entity_type to string value
        if hasattr(doc.get('entity_type'), 'value'):
            doc['entity_type'] = doc['entity_type'].value

        # Convert datetime to ISO format
        for dt_field in ['first_seen', 'last_seen']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        # Convert lists/dicts to JSON
        doc['risk_labels'] = Json(doc.get('risk_labels', []))
        doc['metadata'] = Json(doc.get('metadata', {}))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.entities
                (entity_id, entity_type, raw_value, normalized_value, first_seen, last_seen,
                 occurrence_count, source_channel, risk_labels, metadata)
                VALUES (%(entity_id)s, %(entity_type)s, %(raw_value)s, %(normalized_value)s,
                        %(first_seen)s, %(last_seen)s, %(occurrence_count)s, %(source_channel)s,
                        %(risk_labels)s, %(metadata)s)
                ON CONFLICT (entity_id) DO UPDATE SET
                    last_seen = NOW(),
                    occurrence_count = {}.entities.occurrence_count + 1,
                    risk_labels = %(risk_labels)s,
                    metadata = %(metadata)s
            """).format(sql.Identifier(self.schema)), {
                'entity_id': entity_id,
                'entity_type': doc['entity_type'],
                'raw_value': doc.get('raw_value'),
                'normalized_value': doc.get('normalized_value'),
                'first_seen': doc.get('first_seen'),
                'last_seen': doc.get('last_seen'),
                'occurrence_count': doc.get('occurrence_count', 0),
                'source_channel': doc.get('source_channel'),
                'risk_labels': doc.get('risk_labels'),
                'metadata': doc.get('metadata'),
            })
        return entity_id

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get an entity by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.entities WHERE entity_id = %s").format(
                sql.Identifier(self.schema)), (entity_id,))
            return cur.fetchone()

    def get_entity_by_value(self, entity_type: str, raw_value: str, source_channel: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get entity by type and value."""
        with self._get_cursor() as cur:
            if source_channel:
                cur.execute(sql.SQL("""
                    SELECT * FROM {}.entities
                    WHERE entity_type = %s AND raw_value = %s AND source_channel = %s
                """).format(sql.Identifier(self.schema)), (entity_type, raw_value, source_channel))
            else:
                cur.execute(sql.SQL("""
                    SELECT * FROM {}.entities
                    WHERE entity_type = %s AND raw_value = %s
                """).format(sql.Identifier(self.schema)), (entity_type, raw_value))
            return cur.fetchone()

    def get_entities_by_type(self, entity_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get entities by type."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT * FROM {}.entities
                WHERE entity_type = %s
                LIMIT %s
            """).format(sql.Identifier(self.schema)), (entity_type, limit))
            return cur.fetchall()

    def get_entity_profile(self, entity_id: str, relation_depth: int = 1) -> Optional[Dict[str, Any]]:
        """Get entity profile with related entities."""
        entity = self.get_entity(entity_id)
        if not entity:
            return None

        # Get related message refs
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.message_refs WHERE entity_id = %s").format(
                sql.Identifier(self.schema)), (entity_id,))
            refs = cur.fetchall()

        # Get related entities from refs
        related_entities = []
        entity_ids = list(set([ref["entity_id"] for ref in refs]))
        if entity_ids:
            with self._get_cursor() as cur:
                placeholders = ','.join(['%s'] * len(entity_ids))
                cur.execute(sql.SQL(f"""
                    SELECT * FROM {self.schema}.entities
                    WHERE entity_id IN ({placeholders})
                """).as_string(self._conn), entity_ids)
                related = cur.fetchall()
                related_entities = [e for e in related if e["entity_id"] != entity_id]

        # Get risk distribution
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT risk_label, COUNT(*) as count
                FROM {}.message_refs
                WHERE entity_id = %s AND risk_label IS NOT NULL
                GROUP BY risk_label
            """).format(sql.Identifier(self.schema)), (entity_id,))
            risk_distribution = cur.fetchall()

        # Get recent evidence
        message_ids = [ref["message_id"] for ref in refs]
        recent_clues = []
        if message_ids:
            with self._get_cursor() as cur:
                placeholders = ','.join(['%s'] * min(len(message_ids), 10))
                cur.execute(sql.SQL(f"""
                    SELECT clue_id, published_at, raw_text FROM {self.schema}.clues
                    WHERE message_id IN ({placeholders})
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT 5
                """).as_string(self._conn), message_ids[:10])
                recent_clues = cur.fetchall()

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
                    "snippet": (c.get("raw_text") or "")[:200]
                }
                for c in recent_clues
            ]
        }

    def get_total_entities_count(self) -> int:
        """Get total count of entities."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT COUNT(*) as cnt FROM {}.entities").format(
                sql.Identifier(self.schema)))
            return cur.fetchone()['cnt']

    # ========== MessageRef Operations ==========

    def insert_message_ref(self, ref: MessageRef) -> str:
        """Insert a message reference."""
        doc = ref.to_dict()
        ref_id = doc.pop("ref_id")

        if isinstance(doc.get('created_at'), datetime):
            doc['created_at'] = doc['created_at'].isoformat()

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.message_refs
                (ref_id, entity_id, message_id, source, context_snippet, risk_label, created_at)
                VALUES (%(ref_id)s, %(entity_id)s, %(message_id)s, %(source)s,
                        %(context_snippet)s, %(risk_label)s, %(created_at)s)
            """).format(sql.Identifier(self.schema)), {
                'ref_id': ref_id,
                'entity_id': doc['entity_id'],
                'message_id': doc['message_id'],
                'source': doc.get('source'),
                'context_snippet': doc.get('context_snippet'),
                'risk_label': doc.get('risk_label'),
                'created_at': doc.get('created_at'),
            })
        return ref_id

    def get_message_refs(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all message refs for an entity."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.message_refs WHERE entity_id = %s").format(
                sql.Identifier(self.schema)), (entity_id,))
            return cur.fetchall()

    # ========== SlangMapping Operations ==========

    def upsert_slang_mapping(self, mapping: SlangMapping) -> str:
        """Insert or update a slang mapping."""
        doc = mapping.to_dict()
        mapping_id = doc.pop("mapping_id")

        # Convert datetime to ISO format
        for dt_field in ['created_at', 'updated_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.slang_mappings
                (mapping_id, slang_raw, meaning, regex_pattern, source, verified, confidence, created_at, updated_at)
                VALUES (%(mapping_id)s, %(slang_raw)s, %(meaning)s, %(regex_pattern)s,
                        %(source)s, %(verified)s, %(confidence)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (slang_raw) DO UPDATE SET
                    meaning = EXCLUDED.meaning,
                    regex_pattern = EXCLUDED.regex_pattern,
                    verified = EXCLUDED.verified,
                    confidence = EXCLUDED.confidence,
                    updated_at = NOW()
            """).format(sql.Identifier(self.schema)), {
                'mapping_id': mapping_id,
                'slang_raw': doc['slang_raw'],
                'meaning': doc.get('meaning'),
                'regex_pattern': doc.get('regex_pattern'),
                'source': doc.get('source', 'preset'),
                'verified': doc.get('verified', False),
                'confidence': doc.get('confidence', 1.0),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
            })
        return mapping_id

    def get_slang_mapping(self, slang_raw: str) -> Optional[Dict[str, Any]]:
        """Get slang mapping by raw term."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.slang_mappings WHERE slang_raw = %s").format(
                sql.Identifier(self.schema)), (slang_raw,))
            return cur.fetchone()

    def get_all_slang_mappings(self, verified_only: bool = True) -> List[Dict[str, Any]]:
        """Get all slang mappings."""
        with self._get_cursor() as cur:
            if verified_only:
                cur.execute(sql.SQL("SELECT * FROM {}.slang_mappings WHERE verified = TRUE").format(
                    sql.Identifier(self.schema)))
            else:
                cur.execute(sql.SQL("SELECT * FROM {}.slang_mappings").format(
                    sql.Identifier(self.schema)))
            return cur.fetchall()

    # ========== SlangCandidate Operations ==========

    def upsert_slang_candidate(self, candidate: SlangCandidate) -> str:
        """Insert or update a slang candidate."""
        doc = candidate.to_dict()
        word = doc.pop("candidate_word")

        # Convert datetime to ISO format
        for dt_field in ['created_at', 'updated_at', 'reject_until']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        # Convert status enum
        if hasattr(doc.get('status'), 'value'):
            doc['status'] = doc['status'].value

        doc['contexts'] = Json(doc.get('contexts', []))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.slang_candidates
                (candidate_word, contexts, occurrence_count, status, inference_count,
                 reject_until, regex_pattern, meaning, source_channel, created_at, updated_at)
                VALUES (%(candidate_word)s, %(contexts)s, %(occurrence_count)s, %(status)s,
                        %(inference_count)s, %(reject_until)s, %(regex_pattern)s, %(meaning)s,
                        %(source_channel)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (candidate_word) DO UPDATE SET
                    contexts = EXCLUDED.contexts,
                    occurrence_count = EXCLUDED.occurrence_count,
                    status = EXCLUDED.status,
                    inference_count = EXCLUDED.inference_count,
                    updated_at = NOW()
            """).format(sql.Identifier(self.schema)), {
                'candidate_word': word,
                'contexts': doc.get('contexts'),
                'occurrence_count': doc.get('occurrence_count', 0),
                'status': doc.get('status', 'NEW'),
                'inference_count': doc.get('inference_count', 0),
                'reject_until': doc.get('reject_until'),
                'regex_pattern': doc.get('regex_pattern'),
                'meaning': doc.get('meaning'),
                'source_channel': doc.get('source_channel'),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
            })
        return word

    def get_slang_candidate(self, word: str) -> Optional[Dict[str, Any]]:
        """Get a slang candidate by word."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.slang_candidates WHERE candidate_word = %s").format(
                sql.Identifier(self.schema)), (word,))
            return cur.fetchone()

    def get_slang_candidates_by_status(self, status: SlangStatus) -> List[Dict[str, Any]]:
        """Get slang candidates by status."""
        status_val = status.value if isinstance(status, SlangStatus) else status
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.slang_candidates WHERE status = %s").format(
                sql.Identifier(self.schema)), (status_val,))
            return cur.fetchall()

    # ========== QueryTask Operations ==========

    def create_query_task(self, task: QueryTask) -> str:
        """Create a new query task."""
        doc = task.to_dict()
        query_id = doc.pop("query_id")

        # Convert datetime to ISO format
        for dt_field in ['created_at', 'updated_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        # Convert status enum
        if hasattr(doc.get('status'), 'value'):
            doc['status'] = doc['status'].value

        # Convert JSON fields
        for json_field in ['parsed_intent', 'execution_plan', 'channels', 'time_range',
                          'risk_types', 'platforms', 'constraints', 'result_stats']:
            doc[json_field] = Json(doc.get(json_field, {}))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.queries
                (query_id, query_text, status, parsed_intent, execution_plan, realtime_fetch,
                 channels, time_range, risk_types, platforms, constraints, progress, stage,
                 message, result_stats, failure_reason, created_at, updated_at)
                VALUES (%(query_id)s, %(query_text)s, %(status)s, %(parsed_intent)s, %(execution_plan)s,
                        %(realtime_fetch)s, %(channels)s, %(time_range)s, %(risk_types)s, %(platforms)s,
                        %(constraints)s, %(progress)s, %(stage)s, %(message)s, %(result_stats)s,
                        %(failure_reason)s, %(created_at)s, %(updated_at)s)
            """).format(sql.Identifier(self.schema)), {
                'query_id': query_id,
                'query_text': doc.get('query_text'),
                'status': doc.get('status', 'PENDING'),
                'parsed_intent': doc.get('parsed_intent'),
                'execution_plan': doc.get('execution_plan'),
                'realtime_fetch': doc.get('realtime_fetch', False),
                'channels': doc.get('channels'),
                'time_range': doc.get('time_range'),
                'risk_types': doc.get('risk_types'),
                'platforms': doc.get('platforms'),
                'constraints': doc.get('constraints'),
                'progress': doc.get('progress', 0),
                'stage': doc.get('stage'),
                'message': doc.get('message'),
                'result_stats': doc.get('result_stats'),
                'failure_reason': doc.get('failure_reason'),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
            })
        return query_id

    def update_query_task(self, query_id: str, updates: Dict[str, Any]) -> bool:
        """Update a query task."""
        updates["updated_at"] = datetime.utcnow().isoformat()

        # Build dynamic update query
        set_clauses = []
        params = {'query_id': query_id}
        for i, (k, v) in enumerate(updates.items()):
            set_clauses.append(f"{k} = %({k})s")
            if isinstance(v, (dict, list)):
                params[k] = json.dumps(v)
            else:
                params[k] = v

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.queries
                SET {}
                WHERE query_id = %(query_id)s
            """).format(
                sql.Identifier(self.schema),
                sql.SQL(', '.join(set_clauses))
            ), params)
            return cur.rowcount > 0

    def get_query_task(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Get a query task by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.queries WHERE query_id = %s").format(
                sql.Identifier(self.schema)), (query_id,))
            return cur.fetchone()

    # ========== Clue Operations ==========

    def insert_clue(self, clue: Clue) -> str:
        """Insert a clue."""
        doc = clue.to_dict()
        clue_id = doc.pop("clue_id")

        # Convert datetime to ISO format
        for dt_field in ['published_at', 'created_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        # Convert JSON fields
        for json_field in ['entity_list', 'slang_mappings', 'graph_relations']:
            doc[json_field] = Json(doc.get(json_field, []))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.clues
                (clue_id, message_id, risk_label_level1, risk_label_level2, confidence,
                 classification_source, raw_text, cleaned_text, classification_reason,
                 source_channel, source_group_id, source_author_id, entity_list,
                 slang_mappings, graph_relations, query_id, platform, published_at, created_at)
                VALUES (%(clue_id)s, %(message_id)s, %(risk_label_level1)s, %(risk_label_level2)s,
                        %(confidence)s, %(classification_source)s, %(raw_text)s, %(cleaned_text)s,
                        %(classification_reason)s, %(source_channel)s, %(source_group_id)s,
                        %(source_author_id)s, %(entity_list)s, %(slang_mappings)s, %(graph_relations)s,
                        %(query_id)s, %(platform)s, %(published_at)s, %(created_at)s)
            """).format(sql.Identifier(self.schema)), {
                'clue_id': clue_id,
                'message_id': doc.get('message_id'),
                'risk_label_level1': doc.get('risk_label_level1'),
                'risk_label_level2': doc.get('risk_label_level2'),
                'confidence': doc.get('confidence'),
                'classification_source': doc.get('classification_source'),
                'raw_text': doc.get('raw_text'),
                'cleaned_text': doc.get('cleaned_text'),
                'classification_reason': doc.get('classification_reason'),
                'source_channel': doc.get('source_channel'),
                'source_group_id': doc.get('source_group_id'),
                'source_author_id': doc.get('source_author_id'),
                'entity_list': doc.get('entity_list'),
                'slang_mappings': doc.get('slang_mappings'),
                'graph_relations': doc.get('graph_relations'),
                'query_id': doc.get('query_id'),
                'platform': doc.get('platform'),
                'published_at': doc.get('published_at'),
                'created_at': doc.get('created_at'),
            })
        return clue_id

    def get_clue(self, clue_id: str) -> Optional[Dict[str, Any]]:
        """Get a clue by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.clues WHERE clue_id = %s").format(
                sql.Identifier(self.schema)), (clue_id,))
            return cur.fetchone()

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
        sort_order: int = -1,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """Get clues with filtering and pagination."""
        conditions = []
        params = {}

        if query_id:
            conditions.append("query_id = %(query_id)s")
            params['query_id'] = query_id
        if risk_label_level1:
            conditions.append("risk_label_level1 = %(risk_label_level1)s")
            params['risk_label_level1'] = risk_label_level1
        if risk_label_level2:
            conditions.append("risk_label_level2 = %(risk_label_level2)s")
            params['risk_label_level2'] = risk_label_level2
        if source_channel:
            conditions.append("source_channel = %(source_channel)s")
            params['source_channel'] = source_channel
        if min_confidence:
            conditions.append("confidence >= %(min_confidence)s")
            params['min_confidence'] = min_confidence
        if start_time:
            conditions.append("published_at >= %(start_time)s")
            params['start_time'] = start_time
        if end_time:
            conditions.append("published_at <= %(end_time)s")
            params['end_time'] = end_time

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Determine sort direction
        sort_dir = "DESC" if sort_order == -1 else "ASC"
        # Quote reserved words
        sort_col = f'"{sort_by}"' if sort_by.lower() in ('desc', 'content') else sort_by

        # Get total count
        with self._get_cursor() as cur:
            count_query = sql.SQL("""
                SELECT COUNT(*) as total FROM {}.clues WHERE {}
            """).format(sql.Identifier(self.schema), sql.SQL(where_clause))
            cur.execute(count_query, params)
            total = cur.fetchone()['total']

        # Get paginated items
        offset = (page_no - 1) * page_size
        params['limit'] = page_size
        params['offset'] = offset

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT * FROM {}.clues
                WHERE {}
                ORDER BY {} {}
                LIMIT %(limit)s OFFSET %(offset)s
            """).format(
                sql.Identifier(self.schema),
                sql.SQL(where_clause),
                sql.Identifier(sort_by),
                sql.SQL(sort_dir)
            ), params)
            items = cur.fetchall()

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def get_clue_count(self) -> int:
        """Get total count of clues."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT COUNT(*) as cnt FROM {}.clues").format(
                sql.Identifier(self.schema)))
            return cur.fetchone()['cnt']

    # ========== Feedback Operations ==========

    def insert_feedback(self, feedback: Feedback) -> str:
        """Insert feedback."""
        doc = feedback.to_dict()
        feedback_id = doc.pop("feedback_id")

        if isinstance(doc.get('created_at'), datetime):
            doc['created_at'] = doc['created_at'].isoformat()

        doc['correct_entities'] = Json(doc.get('correct_entities', []))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.feedback
                (feedback_id, clue_id, feedback_type, correct_risk_label_level1,
                 correct_risk_label_level2, correct_entities, comment, operator,
                 platinum_enrolled, sample_weight, model_update_status, created_at)
                VALUES (%(feedback_id)s, %(clue_id)s, %(feedback_type)s,
                        %(correct_risk_label_level1)s, %(correct_risk_label_level2)s,
                        %(correct_entities)s, %(comment)s, %(operator)s,
                        %(platinum_enrolled)s, %(sample_weight)s, %(model_update_status)s, %(created_at)s)
            """).format(sql.Identifier(self.schema)), {
                'feedback_id': feedback_id,
                'clue_id': doc.get('clue_id'),
                'feedback_type': doc.get('feedback_type'),
                'correct_risk_label_level1': doc.get('correct_risk_label_level1'),
                'correct_risk_label_level2': doc.get('correct_risk_label_level2'),
                'correct_entities': doc.get('correct_entities'),
                'comment': doc.get('comment'),
                'operator': doc.get('operator', ''),
                'platinum_enrolled': doc.get('platinum_enrolled', False),
                'sample_weight': doc.get('sample_weight', 1),
                'model_update_status': doc.get('model_update_status', 'IDLE'),
                'created_at': doc.get('created_at'),
            })
        return feedback_id

    def get_feedback(self, feedback_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.feedback WHERE feedback_id = %s").format(
                sql.Identifier(self.schema)), (feedback_id,))
            return cur.fetchone()

    # ========== SeedWord Operations ==========

    def upsert_seed_word(self, seed_word: SeedWord) -> str:
        """Insert or update a seed word."""
        doc = seed_word.to_dict()
        word = doc.pop("word")

        for dt_field in ['created_at', 'updated_at', 'last_promoted_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        if hasattr(doc.get('status'), 'value'):
            doc['status'] = doc['status'].value

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.seed_words
                (word, status, source, weekly_hit_count, effective_clue_ratio,
                 last_promoted_at, created_at, updated_at)
                VALUES (%(word)s, %(status)s, %(source)s, %(weekly_hit_count)s,
                        %(effective_clue_ratio)s, %(last_promoted_at)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (word) DO UPDATE SET
                    status = EXCLUDED.status,
                    weekly_hit_count = EXCLUDED.weekly_hit_count,
                    effective_clue_ratio = EXCLUDED.effective_clue_ratio,
                    last_promoted_at = EXCLUDED.last_promoted_at,
                    updated_at = NOW()
            """).format(sql.Identifier(self.schema)), {
                'word': word,
                'status': doc.get('status', 'active'),
                'source': doc.get('source', 'preset'),
                'weekly_hit_count': doc.get('weekly_hit_count', 0),
                'effective_clue_ratio': doc.get('effective_clue_ratio', 0.0),
                'last_promoted_at': doc.get('last_promoted_at'),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
            })
        return word

    def get_seed_word(self, word: str) -> Optional[Dict[str, Any]]:
        """Get a seed word."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.seed_words WHERE word = %s").format(
                sql.Identifier(self.schema)), (word,))
            return cur.fetchone()

    def get_seed_words(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Get seed words with filtering."""
        conditions = []
        params = {}

        if status:
            conditions.append("status = %(status)s")
            params['status'] = status
        if source:
            conditions.append("source = %(source)s")
            params['source'] = source

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_cursor() as cur:
            # Count total
            cur.execute(sql.SQL("""
                SELECT COUNT(*) as total FROM {}.seed_words WHERE {}
            """).format(sql.Identifier(self.schema), sql.SQL(where_clause)), params)
            total = cur.fetchone()['total']

            # Get paginated items
            offset = (page_no - 1) * page_size
            params['limit'] = page_size
            params['offset'] = offset

            cur.execute(sql.SQL("""
                SELECT * FROM {}.seed_words
                WHERE {}
                LIMIT %(limit)s OFFSET %(offset)s
            """).format(sql.Identifier(self.schema), sql.SQL(where_clause)), params)
            items = cur.fetchall()

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def promote_seed_word(self, word: str, operator: str, reason: Optional[str] = None) -> bool:
        """Promote a seed word to active status."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.seed_words
                SET status = %s, last_promoted_at = %s
                WHERE word = %s
            """).format(sql.Identifier(self.schema)),
                        (SeedWordStatus.ACTIVE.value, datetime.utcnow(), word))
            return cur.rowcount > 0

    # ========== Proposal Operations ==========

    def insert_proposal(self, proposal: Proposal) -> str:
        """Insert a proposal."""
        doc = proposal.to_dict()
        proposal_id = doc.pop("proposal_id")

        for dt_field in ['created_at', 'processed_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.proposals
                (proposal_id, proposal_type, title, detail, status, created_at, processed_at, operator, comment)
                VALUES (%(proposal_id)s, %(proposal_type)s, %(title)s, %(detail)s,
                        %(status)s, %(created_at)s, %(processed_at)s, %(operator)s, %(comment)s)
            """).format(sql.Identifier(self.schema)), {
                'proposal_id': proposal_id,
                'proposal_type': doc.get('proposal_type'),
                'title': doc.get('title'),
                'detail': doc.get('detail'),
                'status': doc.get('status', 'pending'),
                'created_at': doc.get('created_at'),
                'processed_at': doc.get('processed_at'),
                'operator': doc.get('operator'),
                'comment': doc.get('comment'),
            })
        return proposal_id

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get a proposal by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.proposals WHERE proposal_id = %s").format(
                sql.Identifier(self.schema)), (proposal_id,))
            return cur.fetchone()

    def get_proposals(
        self,
        proposal_type: Optional[str] = None,
        status: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Get proposals with filtering."""
        conditions = []
        params = {}

        if proposal_type:
            conditions.append("proposal_type = %(proposal_type)s")
            params['proposal_type'] = proposal_type
        if status:
            conditions.append("status = %(status)s")
            params['status'] = status

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT COUNT(*) as total FROM {}.proposals WHERE {}
            """).format(sql.Identifier(self.schema), sql.SQL(where_clause)), params)
            total = cur.fetchone()['total']

            offset = (page_no - 1) * page_size
            params['limit'] = page_size
            params['offset'] = offset

            cur.execute(sql.SQL("""
                SELECT * FROM {}.proposals
                WHERE {}
                ORDER BY created_at DESC
                LIMIT %(limit)s OFFSET %(offset)s
            """).format(sql.Identifier(self.schema), sql.SQL(where_clause)), params)
            items = cur.fetchall()

        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "items": items
        }

    def approve_proposal(self, proposal_id: str, operator: str, comment: Optional[str] = None) -> bool:
        """Approve a proposal."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.proposals
                SET status = 'approved', processed_at = %s, operator = %s, comment = %s
                WHERE proposal_id = %s AND status = 'pending'
            """).format(sql.Identifier(self.schema)),
                        (datetime.utcnow(), operator, comment, proposal_id))
            return cur.rowcount > 0

    # ========== ExportTask Operations ==========

    def create_export_task(self, task: ExportTask) -> str:
        """Create an export task."""
        doc = task.to_dict()
        export_id = doc.pop("export_id")

        if isinstance(doc.get('created_at'), datetime):
            doc['created_at'] = doc['created_at'].isoformat()
        if isinstance(doc.get('expire_at'), datetime):
            doc['expire_at'] = doc['expire_at'].isoformat()

        if hasattr(doc.get('status'), 'value'):
            doc['status'] = doc['status'].value

        doc['filters'] = Json(doc.get('filters', {}))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.exports
                (export_id, query_id, filters, export_format, include_graph_relations,
                 operator, status, download_url, expire_at, created_at)
                VALUES (%(export_id)s, %(query_id)s, %(filters)s, %(export_format)s,
                        %(include_graph_relations)s, %(operator)s, %(status)s,
                        %(download_url)s, %(expire_at)s, %(created_at)s)
            """).format(sql.Identifier(self.schema)), {
                'export_id': export_id,
                'query_id': doc.get('query_id'),
                'filters': doc.get('filters'),
                'export_format': doc.get('export_format', 'json'),
                'include_graph_relations': doc.get('include_graph_relations', False),
                'operator': doc.get('operator', ''),
                'status': doc.get('status', 'PENDING'),
                'download_url': doc.get('download_url'),
                'expire_at': doc.get('expire_at'),
                'created_at': doc.get('created_at'),
            })
        return export_id

    def update_export_task(self, export_id: str, updates: Dict[str, Any]) -> bool:
        """Update an export task."""
        set_clauses = []
        params = {'export_id': export_id}
        for k, v in updates.items():
            set_clauses.append(f"{k} = %({k})s")
            if isinstance(v, (dict, list)):
                params[k] = json.dumps(v)
            else:
                params[k] = v

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.exports
                SET {}
                WHERE export_id = %(export_id)s
            """).format(
                sql.Identifier(self.schema),
                sql.SQL(', '.join(set_clauses))
            ), params)
            return cur.rowcount > 0

    def get_export_task(self, export_id: str) -> Optional[Dict[str, Any]]:
        """Get an export task."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.exports WHERE export_id = %s").format(
                sql.Identifier(self.schema)), (export_id,))
            return cur.fetchone()

    # ========== Channel Operations ==========

    def upsert_channel(self, channel: Channel) -> str:
        """Insert or update a channel."""
        doc = channel.to_dict()
        platform = doc.pop("platform")

        if isinstance(doc.get('configured_at'), datetime):
            doc['configured_at'] = doc['configured_at'].isoformat()
        if isinstance(doc.get('last_polling_at'), datetime):
            doc['last_polling_at'] = doc['last_polling_at'].isoformat()

        doc['config'] = Json(doc.get('config', {}))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.channels
                (platform, platform_name, category, status, enabled, config,
                 configured_at, messages_today, last_polling_at, error_message)
                VALUES (%(platform)s, %(platform_name)s, %(category)s, %(status)s,
                        %(enabled)s, %(config)s, %(configured_at)s, %(messages_today)s,
                        %(last_polling_at)s, %(error_message)s)
                ON CONFLICT (platform) DO UPDATE SET
                    platform_name = EXCLUDED.platform_name,
                    category = EXCLUDED.category,
                    status = EXCLUDED.status,
                    enabled = EXCLUDED.enabled,
                    config = EXCLUDED.config,
                    configured_at = EXCLUDED.configured_at,
                    messages_today = EXCLUDED.messages_today,
                    last_polling_at = EXCLUDED.last_polling_at,
                    error_message = EXCLUDED.error_message
            """).format(sql.Identifier(self.schema)), {
                'platform': platform,
                'platform_name': doc.get('platform_name'),
                'category': doc.get('category'),
                'status': doc.get('status', 'unconfigured'),
                'enabled': doc.get('enabled', False),
                'config': doc.get('config'),
                'configured_at': doc.get('configured_at'),
                'messages_today': doc.get('messages_today', 0),
                'last_polling_at': doc.get('last_polling_at'),
                'error_message': doc.get('error_message'),
            })
        return platform

    def get_channel(self, platform: str) -> Optional[Dict[str, Any]]:
        """Get a channel by platform."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.channels WHERE platform = %s").format(
                sql.Identifier(self.schema)), (platform,))
            return cur.fetchone()

    def get_all_channels(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all channels."""
        with self._get_cursor() as cur:
            if category:
                cur.execute(sql.SQL("SELECT * FROM {}.channels WHERE category = %s").format(
                    sql.Identifier(self.schema)), (category,))
            else:
                cur.execute(sql.SQL("SELECT * FROM {}.channels").format(
                    sql.Identifier(self.schema)))
            return cur.fetchall()

    # ========== Metrics Operations ==========

    def upsert_metrics(self, metrics: Metrics) -> str:
        """Insert or update daily metrics."""
        doc = metrics.to_dict()
        date = doc.pop("date")

        if isinstance(doc.get('updated_at'), datetime):
            doc['updated_at'] = doc['updated_at'].isoformat()
        if isinstance(doc.get('last_patrol_at'), datetime):
            doc['last_patrol_at'] = doc['last_patrol_at'].isoformat()

        if hasattr(doc.get('background_patrol_status'), 'value'):
            doc['background_patrol_status'] = doc['background_patrol_status'].value

        doc['classification_distribution'] = Json(doc.get('classification_distribution', []))
        doc['channel_status'] = Json(doc.get('channel_status', []))

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.metrics
                (date, token_usage_today, token_remaining_percent, collection_success_rate,
                 total_entities, total_relations, messages_processed_today,
                 background_patrol_status, last_patrol_at, classification_distribution,
                 channel_status, updated_at)
                VALUES (%(date)s, %(token_usage_today)s, %(token_remaining_percent)s,
                        %(collection_success_rate)s, %(total_entities)s, %(total_relations)s,
                        %(messages_processed_today)s, %(background_patrol_status)s,
                        %(last_patrol_at)s, %(classification_distribution)s,
                        %(channel_status)s, %(updated_at)s)
                ON CONFLICT (date) DO UPDATE SET
                    token_usage_today = EXCLUDED.token_usage_today,
                    token_remaining_percent = EXCLUDED.token_remaining_percent,
                    collection_success_rate = EXCLUDED.collection_success_rate,
                    total_entities = EXCLUDED.total_entities,
                    total_relations = EXCLUDED.total_relations,
                    messages_processed_today = EXCLUDED.messages_processed_today,
                    background_patrol_status = EXCLUDED.background_patrol_status,
                    last_patrol_at = EXCLUDED.last_patrol_at,
                    classification_distribution = EXCLUDED.classification_distribution,
                    channel_status = EXCLUDED.channel_status,
                    updated_at = NOW()
            """).format(sql.Identifier(self.schema)), {
                'date': date,
                'token_usage_today': doc.get('token_usage_today', 0),
                'token_remaining_percent': doc.get('token_remaining_percent', 1.0),
                'collection_success_rate': doc.get('collection_success_rate', 1.0),
                'total_entities': doc.get('total_entities', 0),
                'total_relations': doc.get('total_relations', 0),
                'messages_processed_today': doc.get('messages_processed_today', 0),
                'background_patrol_status': doc.get('background_patrol_status', 'IDLE'),
                'last_patrol_at': doc.get('last_patrol_at'),
                'classification_distribution': doc.get('classification_distribution'),
                'channel_status': doc.get('channel_status'),
                'updated_at': doc.get('updated_at'),
            })
        return date

    def get_metrics(self, date: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific date."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.metrics WHERE date = %s").format(
                sql.Identifier(self.schema)), (date,))
            return cur.fetchone()

    def get_latest_metrics(self) -> Optional[Dict[str, Any]]:
        """Get the latest metrics."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT * FROM {}.metrics
                ORDER BY date DESC
                LIMIT 1
            """).format(sql.Identifier(self.schema)))
            return cur.fetchone()

    # ========== AutoEvolution Operations ==========

    def get_auto_evolution_status(self) -> Dict[str, Any]:
        """Get auto evolution status."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("SELECT * FROM {}.auto_evolution WHERE id = 'status'").format(
                sql.Identifier(self.schema)))
            status = cur.fetchone()

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

        if 'retrain_status' in updates and hasattr(updates['retrain_status'], 'value'):
            updates['retrain_status'] = updates['retrain_status'].value

        set_clauses = []
        params = {'id': 'status'}
        for k, v in updates.items():
            set_clauses.append(f"{k} = %({k})s")
            params[k] = v

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.auto_evolution
                SET {}
                WHERE id = 'status'
            """).format(
                sql.Identifier(self.schema),
                sql.SQL(', '.join(set_clauses))
            ), params)

            if cur.rowcount == 0:
                # Insert if not exists
                params['id'] = 'status'
                placeholders = ', '.join([f"%({k})s" for k in params.keys()])
                cur.execute(sql.SQL(f"""
                    INSERT INTO {self.schema}.auto_evolution (id, {', '.join(params.keys())})
                    VALUES ({placeholders})
                """).as_string(self._conn), params)

            return True

    # ========== System Status ==========

    def get_system_ready_status(self) -> Dict[str, Any]:
        """Get system ready status."""
        entity_count = self.get_total_entities_count()

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
        if self._conn:
            self._conn.close()
            self._conn = None

    # ========== Conversation Operations ==========

    def create_conversation(self, conversation: 'Conversation') -> str:
        """Create a new conversation."""
        doc = conversation.to_dict()
        conversation_id = doc.pop("conversation_id")

        for dt_field in ['created_at', 'updated_at']:
            if isinstance(doc.get(dt_field), datetime):
                doc[dt_field] = doc[dt_field].isoformat()

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                INSERT INTO {}.conversations
                (conversation_id, title, messages, timeline, created_at, updated_at)
                VALUES (%(conversation_id)s, %(title)s, %(messages)s, %(timeline)s, %(created_at)s, %(updated_at)s)
            """).format(sql.Identifier(self.schema)), {
                'conversation_id': conversation_id,
                'title': doc.get('title', ''),
                'messages': Json(doc.get('messages', [])),
                'timeline': Json(doc.get('timeline', [])),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
            })

        return conversation_id

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by ID."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT conversation_id, title, messages, timeline, created_at, updated_at
                FROM {}.conversations
                WHERE conversation_id = %(conversation_id)s
            """).format(sql.Identifier(self.schema)), {
                'conversation_id': conversation_id
            })
            row = cur.fetchone()
            return dict(row) if row else None

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List conversations ordered by created_at desc."""
        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT conversation_id, title, created_at, updated_at
                FROM {}.conversations
                ORDER BY created_at DESC
                LIMIT %(limit)s
            """).format(sql.Identifier(self.schema)), {
                'limit': limit
            })
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def update_conversation(self, conversation_id: str, messages: list = None, timeline: list = None, title: str = None) -> bool:
        """Update a conversation."""
        updates = []
        values = {'conversation_id': conversation_id}

        if messages is not None:
            updates.append("messages = %(messages)s")
            values['messages'] = Json(messages)

        if timeline is not None:
            updates.append("timeline = %(timeline)s")
            values['timeline'] = Json(timeline)

        if title is not None:
            updates.append("title = %(title)s")
            values['title'] = title

        if not updates:
            return False

        updates.append("updated_at = NOW()")

        with self._get_cursor() as cur:
            cur.execute(sql.SQL("""
                UPDATE {}.conversations
                SET {}
                WHERE conversation_id = %(conversation_id)s
            """).format(sql.Identifier(self.schema), sql.SQL(", ").join(sql.SQL(u) for u in updates)), values)

        return True

    @classmethod
    def get_instance(cls) -> 'PostgreSQLService':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Alias for backward compatibility
MongoDBService = PostgreSQLService
