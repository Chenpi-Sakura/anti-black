"""
AntiBlack Daemon Scheduler - 24/7 Background Patrol Service
Manages all scheduled background tasks using asyncio.
"""
import asyncio
import logging
import signal
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config import get_config

logger = logging.getLogger(__name__)


class DaemonScheduler:
    """
    Unified scheduler for AntiBlack 24/7 background patrol.

    Manages:
    - Content collection (every 15 minutes per platform)
    - Slang evolution (every 1 hour)
    - LLM error book sampling (daily at 2 AM)
    - Model retraining check (every 12 hours)
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self.kafka_manager = None
        self._slang_learner = None
        self._browser_automator = None

    async def start(self):
        """Start all scheduled tasks."""
        logger.info("=" * 60)
        logger.info("AntiBlack Daemon starting...")
        logger.info("=" * 60)

        self._running = True

        # Initialize components
        await self._initialize_components()

        # Start all loops
        self._tasks.append(asyncio.create_task(self._kafka_consumer_loop()))
        self._tasks.append(asyncio.create_task(self._slang_evolution_loop()))
        self._tasks.append(asyncio.create_task(self._error_book_loop()))
        self._tasks.append(asyncio.create_task(self._retrain_check_loop()))

        logger.info(f"Started {len(self._tasks)} background tasks")

        # Schedule browser automation if enabled
        if self.config.get('daemon', {}).get('browser_automation', {}).get('enabled', False):
            self._tasks.append(asyncio.create_task(self._browser_automation_loop()))

    async def _initialize_components(self):
        """Initialize shared components."""
        # Initialize Kafka manager
        from services.kafka_service import KafkaManager
        kafka_servers = self.config.get('kafka', {}).get('bootstrap_servers', 'localhost:9092')
        self.kafka_manager = KafkaManager(bootstrap_servers=kafka_servers, config=self.config)
        await self.kafka_manager.start()
        logger.info("Kafka Manager initialized")

        # Initialize SlangLearner
        from pipeline.slang_learning import SlangLearner
        from services.database import PostgreSQLService

        pg_db = PostgreSQLService.get_instance()
        existing_mappings = {m['slang_raw']: m['meaning'] for m in pg_db.get_all_slang_mappings()}
        self._slang_learner = SlangLearner(self.config, slang_mappings=existing_mappings)
        logger.info("SlangLearner initialized")

    async def stop(self):
        """Gracefully stop all tasks."""
        logger.info("AntiBlack Daemon stopping...")
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Finalize components
        if self.kafka_manager:
            await self.kafka_manager.stop()

        logger.info("AntiBlack Daemon stopped")

    async def _kafka_consumer_loop(self):
        """Consume messages from Kafka raw.messages topic continuously."""
        topic = self.config.get('kafka', {}).get('topics', {}).get('raw_messages', 'raw.messages')
        group_id = self.config.get('kafka', {}).get('consumer_group', 'antiblack_pipeline')
        
        logger.info(f"Kafka consumer loop started for topic: {topic}, group: {group_id}")
        
        consumer = self.kafka_manager.get_consumer(topic, group_id)
        await consumer.start()

        while self._running:
            try:
                # Consume messages in small batches
                await consumer.consume(self._process_kafka_message, max_messages=50)
            except Exception as e:
                logger.error(f"Kafka consume error: {e}", exc_info=True)
                
            await asyncio.sleep(1)

    async def _process_kafka_message(self, msg: Dict[str, Any]):
        """Handler for single Kafka message."""
        try:
            await self._process_messages([msg])
        except Exception as e:
            logger.error(f"Failed to process message {msg.get('message_id')}: {e}")

    async def _process_messages(self, messages: List[Dict[str, Any]]):
        """Process messages through the full pipeline."""
        from pipeline.cleaner import Cleaner
        from pipeline.classifier import Classifier
        from pipeline.extractor import Extractor
        from pipeline.router import Router
        from services.database import PostgreSQLService
        from models import Clue
        from utils import generate_id

        cleaner = Cleaner()
        classifier = Classifier()
        extractor = Extractor()
        router = Router()
        pg_db = PostgreSQLService.get_instance()

        # Clean
        cleaned_messages = cleaner.clean(messages)

        # Classify
        classification_results = []
        for msg in cleaned_messages:
            result = classifier.classify(msg.cleaned_text, {"source_channel": msg.source_channel})
            classification_results.append(result)

        # Extract
        extraction_results = []
        for msg in cleaned_messages:
            result = extractor.extract(msg.message_id, msg.cleaned_text)
            extraction_results.append(result)

        # Route
        route_results = []
        for i, msg in enumerate(cleaned_messages):
            msg_context = {
                "message_id": msg.message_id,
                "source_channel": msg.source_channel,
                "risk_level": classification_results[i].level1_label,
                "entities": [{"type": e.entity_type} for e in extraction_results[i].entities],
                "slang_mappings": [{"slang": s.slang} for s in extraction_results[i].slang_mappings],
                "raw_text": msg.original_text,
                "cleaned_text": msg.cleaned_text,
            }
            channel = router.route(msg_context)
            route_results.append(channel)

        # Insert clues
        clues_inserted = 0
        for i, msg in enumerate(cleaned_messages):
            try:
                published_at = msg.published_at
                if isinstance(published_at, str):
                    try:
                        from datetime import timezone
                        published_at = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        published_at = None

                clue = Clue(
                    clue_id=generate_id("clue"),
                    message_id=msg.message_id,
                    risk_label_level1=classification_results[i].level1_label or "未分类",
                    risk_label_level2=classification_results[i].level2_label or "其他",
                    confidence=classification_results[i].confidence,
                    classification_source=classification_results[i].source,
                    raw_text=msg.original_text,
                    cleaned_text=msg.cleaned_text,
                    classification_reason=classification_results[i].reason,
                    source_channel=msg.source_channel,
                    source_group_id=msg.group_id,
                    source_author_id=msg.author_id,
                    entity_list=[{"entity_type": e.entity_type, "entity_value": e.entity_value, "source": "extractor"} for e in extraction_results[i].entities],
                    slang_mappings=[{"slang": s.slang, "meaning": s.meaning} for s in extraction_results[i].slang_mappings],
                    query_id=None,
                    platform=msg.metadata.get("platform") if msg.metadata else None,
                    published_at=published_at
                )
                pg_db.insert_clue(clue)
                clues_inserted += 1
            except Exception as e:
                logger.warning(f"Failed to insert clue for {msg.message_id}: {e}")

        logger.info(f"Inserted {clues_inserted} clues into database")

        # Slang learning
        for msg in cleaned_messages:
            self._slang_learner.process_text(msg.cleaned_text, source_channel=msg.source_channel)

        # Update metrics
        from models import Metrics
        from psycopg2 import sql

        today = datetime.now().date().isoformat()
        total_entities = pg_db.get_total_entities_count()

        with pg_db._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT risk_label_level1, COUNT(*) as count
                FROM {}.clues
                GROUP BY risk_label_level1
            """).format(sql.Identifier(pg_db.schema)))
            rows = cur.fetchall()
            distribution = [{"risk_label_level1": row["risk_label_level1"], "count": row["count"]} for row in rows]

        metrics = Metrics(
            date=today,
            token_usage_today=0,
            token_remaining_percent=1.0,
            collection_success_rate=1.0,
            total_entities=total_entities,
            total_relations=0,
            messages_processed_today=clues_inserted,
            classification_distribution=distribution,
            channel_status=[]
        )
        pg_db.upsert_metrics(metrics)

        # Deep channel processing
        deep_messages = [msg for msg, channel in zip(cleaned_messages, route_results) if channel == 'deep']
        if deep_messages:
            await self._process_deep_channel(deep_messages, classification_results, extraction_results, route_results)

    async def _process_deep_channel(self, messages, classification_results, extraction_results, route_results):
        """Process messages through LightRAG deep channel."""
        from services.lightrag_service import GraphProcessor

        graph_processor = GraphProcessor(self.config)
        await graph_processor.initialize()

        for i, msg in enumerate(messages):
            if route_results[i] == 'deep':
                idx = messages.index(msg)
                await graph_processor.process_message({
                    "message_id": msg.message_id,
                    "raw_text": msg.original_text,
                    "cleaned_text": msg.cleaned_text,
                    "classification": {
                        "level1_label": classification_results[idx].level1_label,
                        "level2_label": classification_results[idx].level2_label
                    },
                    "entities": [
                        {"entity_type": e.entity_type, "entity_value": e.entity_value}
                        for e in extraction_results[idx].entities
                    ]
                })

        await graph_processor.finalize()

    async def _slang_evolution_loop(self):
        """Validate pending slang candidates every hour."""
        interval = self.config.get('daemon', {}).get('slang_evolution_interval_seconds', 3600)
        logger.info(f"Slang evolution loop started (interval: {interval}s)")

        while self._running:
            await asyncio.sleep(interval)

            try:
                if self._slang_learner:
                    confirmed = await self._slang_learner.validate_pending_candidates()
                    if confirmed:
                        await self._persist_confirmed_slang(confirmed)
                        logger.info(f"LLM validated {len(confirmed)} new CONFIRMED slang")

                    stats = self._slang_learner.get_candidate_stats()
                    logger.info(f"Slang learning stats: {stats}")
            except Exception as e:
                logger.error(f"Slang evolution error: {e}", exc_info=True)

    async def _persist_confirmed_slang(self, candidates):
        """Persist confirmed slang to database."""
        from services.database import PostgreSQLService
        from models import SlangCandidate as DBSlangCandidate, SlangMapping as DBSlangMapping
        from utils import generate_id

        pg_db = PostgreSQLService.get_instance()

        for candidate in candidates:
            db_candidate = DBSlangCandidate(
                candidate_word=candidate.word,
                contexts=[text for _, text in candidate.contexts],
                occurrence_count=candidate.occurrence_count,
                status=candidate.status,
                inference_count=candidate.inference_count,
                regex_pattern=candidate.regex_pattern,
                meaning=candidate.meaning,
                source_channel=candidate.source_channel
            )
            pg_db.upsert_slang_candidate(db_candidate)

            db_mapping = DBSlangMapping(
                mapping_id=generate_id("slang"),
                slang_raw=candidate.word,
                meaning=candidate.meaning,
                regex_pattern=candidate.regex_pattern,
                source='learned',
                verified=True,
                confidence=1.0
            )
            pg_db.upsert_slang_mapping(db_mapping)
            logger.info(f"Persisted slang: {candidate.word} -> {candidate.meaning}")

            # FR-SLANG-06: LightRAG structured insert
            try:
                from services.lightrag_service import GraphProcessor
                sync_gp = GraphProcessor(self.config)
                await sync_gp.initialize()
                rag_text = f"""黑话: {candidate.word}
释义: {candidate.meaning}
正则: {candidate.regex_pattern}
来源: slang_learning
渠道: {candidate.source_channel}"""
                await sync_gp.lightrag.insert_custom_kg(rag_text, source='slang_learning')
                await sync_gp.finalize()
                logger.info(f"LightRAG sync: {candidate.word}")
            except Exception as e:
                logger.warning(f"LightRAG sync failed for {candidate.word}: {e}")

            # FR-COL-11: Promote to seed word using 7-day frequency (not historical total count)
            try:
                recent_count = pg_db.get_slang_recent_occurrences(
                    word=candidate.word,
                    channel=candidate.source_channel,
                    days=7
                )
                if recent_count >= 100:
                    pg_db.promote_seed_word(
                        word=candidate.word,
                        operator="slang_learning",
                        reason=f"CONFIRMED slang, {recent_count} occurrences in past 7 days"
                    )
                    logger.info(f"Promoted slang to seed word: {candidate.word} (recent_count={recent_count})")
            except Exception as e:
                logger.warning(f"Seed word promotion failed for {candidate.word}: {e}")

    async def _error_book_loop(self):
        """Sample and judge high-confidence clues daily at 2 AM."""
        check_hour = self.config.get('daemon', {}).get('error_book_check_hour', 2)
        logger.info(f"Error book loop started (check hour: {check_hour}:00)")

        while self._running:
            now = datetime.now()
            next_run = now.replace(hour=check_hour, minute=0, second=0, microsecond=0)
            if now.hour >= check_hour:
                next_run += timedelta(days=1)

            sleep_seconds = (next_run - now).total_seconds()
            logger.info(f"Error book sampling scheduled in {sleep_seconds/3600:.1f} hours")

            await asyncio.sleep(sleep_seconds)

            if not self._running:
                break

            try:
                from services.error_book_sampler import ErrorBookSampler
                sampler = ErrorBookSampler(self.config)
                count = await sampler.sample_and_judge()
                logger.info(f"Error book sampling: {count} inconsistencies found")
            except Exception as e:
                logger.error(f"Error book sampling error: {e}", exc_info=True)

    async def _retrain_check_loop(self):
        """Check and trigger model retraining every 12 hours."""
        interval_hours = self.config.get('daemon', {}).get('retrain_check_interval_hours', 12)
        interval_seconds = interval_hours * 3600
        logger.info(f"Retrain check loop started (interval: {interval_hours}h)")

        while self._running:
            await asyncio.sleep(interval_seconds)

            if not self._running:
                break

            try:
                from services.model_retrainer import ModelRetrainer
                retrainer = ModelRetrainer(self.config)
                triggered = await retrainer.check_and_trigger()
                if triggered:
                    logger.info("Model retrain triggered")
            except Exception as e:
                logger.error(f"Retrain check error: {e}", exc_info=True)

    async def _browser_automation_loop(self):
        """Automate browser button clicks for MediaCrawler."""
        from services.browser_automator import BrowserAutomator

        browser_config = self.config.get('daemon', {}).get('browser_automation', {})
        self._browser_automator = BrowserAutomator(
            ws_url=browser_config.get('chrome_ws_url', 'ws://127.0.0.1:9222/devtools/browser')
        )

        logger.info("Browser automation loop started")

        while self._running:
            try:
                await self._browser_automator.connect()
                await self._browser_automator.click_start_button()
                await self._browser_automator.close()
            except Exception as e:
                logger.error(f"Browser automation error: {e}", exc_info=True)

            # Wait before next automation cycle
            await asyncio.sleep(300)  # 5 minutes

    async def _check_token_usage(self):
        """Check token usage and log warning if low."""
        from services.database import PostgreSQLService

        try:
            db = PostgreSQLService.get_instance()
            metrics = db.get_latest_metrics()
            token_usage = metrics.get('token_usage_today', 0) if metrics else 0
            remaining_percent = metrics.get('token_remaining_percent', 1.0) if metrics else 1.0

            if remaining_percent < 0.3:
                logger.warning(f"[TOKEN WARNING] 剩余 Token 不足 30%！当前使用: {token_usage}")
            elif remaining_percent < 0.1:
                logger.error(f"[TOKEN CRITICAL] 剩余 Token 不足 10%！当前使用: {token_usage}")
        except Exception as e:
            logger.error(f"Token usage check error: {e}")


async def run_daemon():
    """Run the daemon with signal handling."""
    config = get_config()
    scheduler = DaemonScheduler(config)

    loop = asyncio.get_event_loop()

    # Setup signal handlers for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(scheduler.stop())
        )

    try:
        await scheduler.start()

        # Keep running until stopped
        while scheduler._running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        if scheduler._running:
            await scheduler.stop()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(run_daemon())