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
        # Pipeline components — instantiated once in _initialize_components()
        # so per-batch reuse avoids reloading the embedding model (50KB pkl)
        # every Kafka poll. Each Classifier() call previously triggered
        # _load_embedding_model() which reads disk and unpickles a joblib blob.
        self._cleaner = None
        self._classifier = None
        self._extractor = None
        self._router = None
        # Dual-queue architecture: clue insertion is the fast path, deep
        # channel (LightRAG) runs in a background worker that drains this
        # queue. Decouples LightRAG's 10-30s latency from clue insertion
        # (~1-2s/batch).
        self._deep_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._graph_processor: Optional[Any] = None  # GraphProcessor (lazy import)

    async def start(self):
        """Start all scheduled tasks."""
        logger.info("=" * 60)
        logger.info("AntiBlack Daemon starting...")
        logger.info("=" * 60)

        self._running = True

        # Initialize components
        await self._initialize_components()

        # Initialize GraphProcessor ONCE (not per-batch) so the LightRAG
        # backend handshake (5-15s) happens once at startup, not on every
        # Kafka batch that has deep-routed messages.
        from services.lightrag_service import GraphProcessor
        self._graph_processor = GraphProcessor(self.config)
        await self._graph_processor.initialize()
        logger.info("GraphProcessor initialized (LightRAG ready)")

        # Start all loops
        self._tasks.append(asyncio.create_task(self._kafka_consumer_loop()))
        self._tasks.append(asyncio.create_task(self._slang_evolution_loop()))
        self._tasks.append(asyncio.create_task(self._slang_to_rule_bridge_loop()))
        self._tasks.append(asyncio.create_task(self._error_book_loop()))
        self._tasks.append(asyncio.create_task(self._retrain_check_loop()))
        # Phase 2.3: daily unknown category discovery
        self._tasks.append(asyncio.create_task(self._unknown_discovery_loop()))
        # Background worker: drains deep_queue and runs batched LightRAG.
        self._tasks.append(asyncio.create_task(self._lightrag_worker_loop()))

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
        self._slang_learner = SlangLearner(
            self.config, slang_mappings=existing_mappings, db_service=pg_db
        )
        logger.info("SlangLearner initialized")

        # Pipeline components (Cleaner / Classifier / Extractor / Router) —
        # instantiated ONCE here so each Kafka batch reuses the same objects
        # instead of rebuilding them. Classifier() in particular triggers
        # _load_embedding_model() which reads + unpickles the latest pkl;
        # doing it per-batch (the old behavior) was a hidden I/O cost that
        # also produced a noisy "Loaded embedding classifier" line in the
        # log on every poll. The instance is thread-safe for our use because
        # Pipeline._process_messages dispatches work via asyncio.to_thread,
        # and sklearn predict is GIL-released for large matrices.
        from pipeline.cleaner import Cleaner
        from pipeline.classifier import Classifier
        from pipeline.extractor import Extractor
        from pipeline.router import Router
        self._cleaner = Cleaner(self.config)
        self._classifier = Classifier(self.config)
        # Extractor takes slang_mappings, not config. Pull them from PG so
        # the Extractor has the same view of slang the rest of the system has.
        self._extractor = Extractor(slang_mappings=existing_mappings)
        self._router = Router(self.config)
        logger.info("Pipeline components initialized (Cleaner/Classifier/Extractor/Router)")

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

        # Finalize GraphProcessor (after worker task is done draining queue)
        if self._graph_processor:
            await self._graph_processor.finalize()
            logger.info("GraphProcessor finalized")

        logger.info("AntiBlack Daemon stopped")

    async def _kafka_consumer_loop(self):
        """Consume messages from Kafka raw.messages topic continuously, in batches.

        Layer 1 batching: getmany() fetches up to BATCH_SIZE messages per
        iteration, fed to _process_messages which is now batch-aware.
        Layer 2 batching: inside _process_messages, classifier.classify_batch
        packs ~8 texts per LLM call (vs 1/call previously).
        Layer 3 pacing: _PacingSemaphore in Classifier.classify_batch
        ensures at most LLM_MAX_CONCURRENT concurrent LLM calls and at
        least LLM_MIN_INTERVAL_SEC between new ones (avoids 429).
        """
        topic = self.config.get('kafka', {}).get('topics', {}).get('raw_messages', 'raw.messages')
        group_id = self.config.get('kafka', {}).get('consumer_group', 'antiblack_pipeline')

        BATCH_SIZE = 20
        POLL_TIMEOUT_MS = 500
        BATCH_MAX_SECONDS = 40  # Kafka session timeout default is 45s; stay below
        NO_MSG_BACKOFF = 0.05

        logger.info(
            f"Kafka consumer loop started: topic={topic}, group={group_id}, "
            f"batch_size={BATCH_SIZE}, poll_timeout_ms={POLL_TIMEOUT_MS}"
        )

        consumer = self.kafka_manager.get_consumer(topic, group_id)
        await consumer.start()
        # Disable auto-commit; we commit manually after each batch is processed.
        # Without this, auto-commit fires every 5s and could commit BEFORE
        # the batch finishes, causing re-consume on restart.
        try:
            consumer._consumer._auto_commit = False
        except Exception:
            pass

        while self._running:
            try:
                loop = asyncio.get_event_loop()
                t0 = loop.time()
                batch = await consumer.getmany(
                    timeout_ms=POLL_TIMEOUT_MS, max_records=BATCH_SIZE,
                )
                if not batch:
                    await asyncio.sleep(NO_MSG_BACKOFF)
                    continue
                await self._process_messages(batch)
                elapsed = loop.time() - t0
                logger.info(
                    f"Processed batch: {len(batch)} messages in {elapsed:.1f}s "
                    f"({len(batch)/max(elapsed,0.001):.1f} msg/s)"
                )
                if elapsed > BATCH_MAX_SECONDS:
                    logger.warning(
                        f"Batch exceeded {BATCH_MAX_SECONDS}s ({elapsed:.1f}s); "
                        f"consider lowering BATCH_SIZE"
                    )
                # Manual commit AFTER batch is processed
                await consumer.commit()
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
        """Process messages through the full pipeline.

        Cleaner / Classifier / Extractor are SYNC and CPU/IO bound (regex,
        Ollama HTTP, sklearn.predict). Calling them directly inside this
        async method would block the event loop for seconds during a
        37k-comment backfill, causing Kafka consumer heartbeat loss and
        group rebalance. Push each to the default ThreadPoolExecutor.

        All four pipeline components (Cleaner/Classifier/Extractor/Router)
        are shared instances created in _initialize_components() — reusing
        them avoids reloading the embedding model on every Kafka poll.
        """
        from services.database import PostgreSQLService
        from models import Clue
        from utils import generate_id

        cleaner = self._cleaner
        classifier = self._classifier
        extractor = self._extractor
        router = self._router
        pg_db = PostgreSQLService.get_instance()

        # Clean — sync, fast (regex + simhash dedup), but still push to thread
        cleaned_messages = await asyncio.to_thread(cleaner.clean, messages)
        if not cleaned_messages:
            return

        # Classify — batched (Layer 2: classifier.classify_batch internally
        # uses 3-stage cascade + 5-10 messages per LLM call + pacing).
        # classify_batch is now async (uses await internally), so call
        # directly with await — no asyncio.to_thread wrapper needed.
        cleaned_texts = [msg.cleaned_text for msg in cleaned_messages]
        classification_results = await classifier.classify_batch(
            cleaned_texts,
            {"source_channel": "batch"},
        )

        # Extract — sync, pure regex, fast but still push to thread
        extraction_results = await asyncio.gather(*[
            asyncio.to_thread(extractor.extract, msg.message_id, msg.cleaned_text)
            for msg in cleaned_messages
        ])

        # Route
        route_results = []
        for i, msg in enumerate(cleaned_messages):
            msg_context = {
                "message_id": msg.message_id,
                "source_channel": msg.source_channel,
                "risk_level": classification_results[i].level1_label,
                "entities": [{"type": e.entity_type} for e in extraction_results[i].entities],
                # extractor returns List[Dict[str, str]] with keys 'slang_raw'
                # and 'meaning' (see pipeline/extractor.py:111-114), NOT a
                # SlangMapping dataclass instance. Pre-existing bug surfaced
                # 2026-06-05 once slang_mappings stopped being empty.
                "slang_mappings": [
                    {"slang": s["slang_raw"], "meaning": s["meaning"]}
                    for s in extraction_results[i].slang_mappings
                ],
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
                    slang_mappings=[
                        {"slang": s["slang_raw"], "meaning": s["meaning"]}
                        for s in extraction_results[i].slang_mappings
                    ],
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

        # Enqueue deep-routed messages for the background LightRAG worker.
        # Clue insertion is now COMPLETE; deep channel happens asynchronously.
        # QueueFull → log + drop (entity extraction is best-effort, not critical path).
        n_deep = 0
        for msg, channel in zip(cleaned_messages, route_results):
            if channel == 'deep':
                try:
                    self._deep_queue.put_nowait({
                        "message_id": msg.message_id,
                        "cleaned_text": msg.cleaned_text,
                        "source_channel": msg.source_channel,
                        "author": msg.author_id,
                        "metadata": msg.metadata,
                    })
                    n_deep += 1
                except asyncio.QueueFull:
                    logger.warning(
                        f"Deep queue full (size={self._deep_queue.qsize()}/1000); "
                        f"dropping {msg.message_id} from LightRAG processing "
                        f"(clue already inserted, entity extraction is best-effort)"
                    )
        if n_deep:
            logger.info(
                f"Enqueued {n_deep} deep messages; queue size={self._deep_queue.qsize()}"
            )

    async def _lightrag_worker_loop(self):
        """Background worker: drain the deep queue, run batched LightRAG processing.

        Decouples LightRAG latency (10-30s per batch) from clue insertion
        (~1-2s/batch). Single worker avoids LightRAG's coarse-grained
        entity-write lock contention (lightrag.py:1750-1762).
        """
        LIGHT_RAG_BATCH = 8
        POLL_TIMEOUT = 1.0

        logger.info(
            f"LightRAG worker loop started (batch_size={LIGHT_RAG_BATCH}, "
            f"poll_timeout={POLL_TIMEOUT}s)"
        )

        while self._running:
            try:
                batch = await self._drain_deep_queue(LIGHT_RAG_BATCH, POLL_TIMEOUT)
                if not batch:
                    continue
                loop = asyncio.get_event_loop()
                t0 = loop.time()
                result = await self._graph_processor.process_batch(batch)
                elapsed = loop.time() - t0
                logger.info(
                    f"LightRAG processed {len(batch)} deep msgs in {elapsed:.1f}s "
                    f"({result['entities']} entities, {result['relationships']} relations)"
                )
            except Exception as e:
                logger.error(f"LightRAG worker error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _drain_deep_queue(self, max_size: int, timeout: float) -> List[Dict[str, Any]]:
        """Block on queue for `timeout`s for first msg, then drain up to `max_size`.

        Pattern: blocking wait on first item gives a natural idle signal
        (no work → no LLM call → no rate pressure), then non-blocking drain
        accumulates whatever else is available up to the batch ceiling.
        """
        try:
            first = await asyncio.wait_for(self._deep_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return []
        batch = [first]
        while len(batch) < max_size:
            try:
                batch.append(self._deep_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _slang_evolution_loop(self):
        """Validate pending slang candidates.

        Trigger model (2026-06-06 调优):
          - 之前: 固定每小时 1 次, 不管 LIKELY 队列大小
          - 之后: 每 60s 检查 LIKELY 队列, ≥ MIN_LIKELY_TO_TRIGGER (5) 立即评估,
            否则等下分钟再看 (idle wait). 实质是事件驱动 + idle fallback.

        收益:
          - 5 条 LIKELY 到达时立即评估 (不等 1h)
          - 没有候选时几乎零开销 (只跑 1 个 count 查询, 60s 一次)
          - 27k LIKELY 现在 1 小时内可评估 3,600 候选 (vs 之前 30/h)

        阈值 MIN_LIKELY_TO_TRIGGER=5 选 5 而非 1:
          - 太小会触发频繁 LLM call (1 个 1 个评估)
          - 5 是 batch_size=200 的 ~2.5%, 避免长尾空闲时反复启 LLM
        """
        check_interval = 60  # 每分钟 polling 一次（idle 时零成本）
        min_likely_to_trigger = 5  # LIKELY 队列 ≥ 5 立即评估
        logger.info(
            f"Slang evolution loop started "
            f"(check_interval={check_interval}s, min_likely={min_likely_to_trigger})"
        )

        while self._running:
            await asyncio.sleep(check_interval)

            if not self._running:
                break

            try:
                if not self._slang_learner:
                    continue
                # Cheap pre-check: count LIKELY candidates before invoking
                # the heavier validate_pending_candidates path.
                likely_count = self._slang_learner.get_likely_count()
                if likely_count < min_likely_to_trigger:
                    logger.debug(
                        f"Slang evolution: {likely_count} LIKELY candidates "
                        f"< threshold {min_likely_to_trigger}, idle wait"
                    )
                    continue

                logger.info(
                    f"Slang evolution: {likely_count} LIKELY candidates "
                    f"≥ threshold {min_likely_to_trigger}, triggering validation"
                )
                confirmed = await self._slang_learner.validate_pending_candidates()
                if confirmed:
                    await self._persist_confirmed_slang(confirmed)
                    logger.info(f"LLM validated {len(confirmed)} new CONFIRMED slang")

                # 末位淘汰：命中率 < 5% 且出现 ≥ 200 次的 CONFIRMED/STABLE
                eliminated = await self._slang_learner.eliminate_weak_slangs()
                if eliminated:
                    logger.info(f"Slang elimination: removed {eliminated} ineffective slangs")

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

            # Note (2026-06-03): 取消 FR-SLANG-06 旧的 LightRAG 写入。
            # 原方案对每个 CONFIRMED slang 调 insert_custom_kg 写一段 4 行
            # "黑话/释义/正则/来源" 自包含文本，但实际只产生孤立 slang
            # 节点（无上下文关联、无共现边），且 PG `slang_mappings` 表 +
            # GIN 索引已提供完整 hybrid 检索能力。LightRAG 此前的价值仅剩
            # "防止 REJECTED 词污染 hybrid 检索"，该需求可由查询阶段
            # `JOIN slang_mappings WHERE status='CONFIRMED'` 替代。
            # 收益：省 1 LLM call/CONFIRMED + Neo4j 写；消除 slang→LightRAG
            # 双向维护链路。

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

    async def _slang_to_rule_bridge_loop(self):
        """Phase 2.2 (FR-EVO-06): daily slang->rule bridge evaluation.

        Evaluates CONFIRMED slangs as Stage 1 rule candidates with LLM
        + Embedding dual-validation. Persists accepted rules to
        antiblack.dynamic_rules, with hit-rate-based auto-rollback.
        """
        interval_hours = self.config.get('slang_to_rule_bridge', {}).get('loop_interval_hours', 24)
        interval_seconds = interval_hours * 3600
        logger.info(f"Slang-to-rule bridge loop started (interval: {interval_hours}h)")

        # First run after a small delay so the daemon has settled
        await asyncio.sleep(60)

        while self._running:
            await asyncio.sleep(interval_seconds)

            if not self._running:
                break

            try:
                from pipeline.slang_to_rule_bridge import SlangToRuleBridge
                bridge = SlangToRuleBridge(config=self.config)
                results = await bridge.evaluate_batch()
                if results:
                    accepted = sum(1 for r in results if r.get('status') == 'accepted')
                    rejected = sum(1 for r in results if r.get('status') == 'rejected')
                    logger.info(
                        f"Slang->rule bridge: evaluated {len(results)} slangs "
                        f"({accepted} accepted, {rejected} rejected)"
                    )
                # Periodic rollback: disable rules with hit_rate < threshold
                try:
                    disabled = bridge.rollback_low_quality_rules()
                    if disabled:
                        logger.info(f"Slang->rule bridge: auto-disabled {disabled} low-quality rules")
                except Exception as e:
                    logger.warning(f"Slang->rule rollback check failed: {e}")
            except Exception as e:
                logger.error(f"Slang->rule bridge error: {e}", exc_info=True)

    async def _unknown_discovery_loop(self):
        """Phase 2.3 (FR-UNK-01..08): daily unknown category discovery.

        Pulls recent 'unknown/other' samples, runs UMAP + HDBSCAN clustering,
        asks LLM to name each cluster (strong constraint prompt), and
        persists accepted proposals to antiblack.pending_category_proposals
        for human review.
        """
        interval_hours = self.config.get('unknown_discovery', {}).get('loop_interval_hours', 24)
        interval_seconds = interval_hours * 3600
        logger.info(f"Unknown discovery loop started (interval: {interval_hours}h)")

        # First run after a small delay so the daemon has settled
        await asyncio.sleep(120)

        while self._running:
            await asyncio.sleep(interval_seconds)

            if not self._running:
                break

            try:
                from pipeline.unknown_discovery import UnknownDiscovery
                ud = UnknownDiscovery(config=self.config)
                proposals = await ud.run()
                if proposals:
                    logger.info(
                        f"Unknown discovery: {len(proposals)} new proposals written "
                        f"(pending human review)"
                    )
                    for p in proposals:
                        logger.info(
                            f"  proposal {p['proposal_id']}: cluster {p['cluster_id']} "
                            f"(n={p['size']}) -> {p['level1']}/{p['level2']} "
                            f"(conf={p['confidence']})"
                        )
            except Exception as e:
                logger.error(f"Unknown discovery error: {e}", exc_info=True)

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
    from utils.logger import configure_root_logger
    configure_root_logger()
    asyncio.run(run_daemon())