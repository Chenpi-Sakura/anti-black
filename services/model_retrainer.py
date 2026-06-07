"""
Model Retrainer - FR-EVO-03
Checks sample counts and triggers model retraining when threshold is reached.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from config import get_config
from services.database import PostgreSQLService
from models import RetrainStatus

logger = logging.getLogger(__name__)


class ModelRetrainer:
    """
    Automated model retraining trigger.

    Checks:
    1. Silver sample count (high-confidence confirmed clues with feedback)
    2. Platinum sample count (manually verified samples)
    3. Error book count (LLM-judged inconsistencies)

    When silver + platinum >= threshold (default 2000), triggers retraining.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._db = None
        # CR-fix (2026-06-07): serialize retrain invocations so two
        # concurrent check_and_trigger() callers can't both pass the
        # threshold check and spawn parallel _run_retrain tasks racing
        # on the same model artifact. asyncio.Lock is fine here
        # because the lock is held briefly (only for the threshold
        # check + asyncio.create_task), not during the 5-10 min
        # training itself.
        self._retrain_lock = asyncio.Lock()
        # Track in-flight retrain so check_and_trigger can short-circuit
        # if a previous run hasn't finished.
        self._retrain_in_flight: bool = False

    async def initialize(self):
        """Initialize database connection."""
        self._db = PostgreSQLService.get_instance()

    async def check_and_trigger(self) -> bool:
        """
        Check if retraining threshold is reached and trigger if so.

        P2 (2026-06-07): threshold logic changed from "absolute total ≥ 2000"
        to "delta from last retrain ≥ 1000". Absolute-threshold logic
        made the loop only fire 1-2 times per week; delta-threshold
        makes it fire whenever a meaningful amount of new silver data
        has accumulated (more responsive to the 1200-sample floor the
        embedding classifier was trained on).

        P0-2: psycopg2 is sync — wrap DB counts in to_thread so the
        asyncio event loop isn't blocked by 4+ SQL queries.
        """
        if not self._db:
            await self.initialize()

        # Threshold = delta from last retrain (not absolute total).
        # Default 1000 — enough for a meaningful retrain without
        # over-triggering (each retrain is 5-10 min).
        delta_threshold = self.config.get('auto_evolution', {}).get(
            'retrain', {}
        ).get('delta_threshold', 1000)

        # Get current counts (sync DB, wrapped in to_thread)
        silver_count = await asyncio.to_thread(self._db.count_silver_samples)
        platinum_count = await asyncio.to_thread(self._db.count_platinum_samples)
        total = silver_count + platinum_count

        # Get last retrain's snapshot count from auto_evolution table
        last_total = await asyncio.to_thread(self._db.get_last_retrain_silver_total)
        if last_total is None:
            # First retrain ever: trigger if we have enough to bootstrap
            delta = total
        else:
            delta = total - last_total

        logger.info(
            f"Retrain check: silver={silver_count}, platinum={platinum_count}, "
            f"total={total}, delta={delta}, threshold={delta_threshold}"
        )

        if delta < delta_threshold:
            return False

        # Threshold reached - try to acquire the retrain lock
        # CR-fix (2026-06-07): prevent two coroutines from both
        # passing the threshold and racing on the model artifact.
        if self._retrain_in_flight:
            logger.info(
                "Retrain already in flight (asyncio.Task running); "
                "skipping duplicate trigger"
            )
            return False
        if self._retrain_lock.locked():
            logger.info("Retrain lock already held; skipping duplicate trigger")
            return False

        async with self._retrain_lock:
            # Double-check after acquiring the lock (another caller
            # may have triggered between our threshold check and
            # lock acquisition).
            if self._retrain_in_flight:
                return False
            self._retrain_in_flight = True
            snapshot_to_use = total

        # Threshold reached - trigger retraining
        logger.info(f"Retrain delta reached: {delta} new samples, triggering retrain")

        # Update status to TRIGGERED (sync DB, in to_thread)
        await asyncio.to_thread(
            self._db.update_auto_evolution_status,
            {'retrain_status': RetrainStatus.TRIGGERED}
        )

        # Trigger async retraining (non-blocking, fire-and-forget)
        asyncio.create_task(
            self._run_retrain_wrapper(snapshot_to_use)
        )

        return True

    async def _run_retrain_wrapper(self, snapshot_total: int):
        """Wrap _run_retrain so the in-flight flag is cleared on exit.

        Without this, a crash inside _run_retrain would leave
        _retrain_in_flight=True forever, blocking all future retrains.
        """
        try:
            await self._run_retrain(snapshot_total=snapshot_total)
        finally:
            self._retrain_in_flight = False

    async def _run_retrain(self, snapshot_total: int = 0):
        """
        Execute model retraining pipeline.

        Runs as a fire-and-forget asyncio.Task (P2, 2026-06-07).
        Doesn't block the daemon. DB ops are wrapped in
        asyncio.to_thread() to keep the event loop free.

        Args:
            snapshot_total: silver+platinum total at the moment we
                decided to trigger. Persisted to auto_evolution after
                success so the next check_and_trigger can compute
                delta from this baseline.
        """
        try:
            logger.info("Starting model retraining...")

            # Import retrain components
            from pipeline.classifier import Classifier
            from models import Feedback

            # Get training data (P0-2: to_thread)
            silver_samples = await asyncio.to_thread(self._db.get_silver_samples)
            platinum_samples = await asyncio.to_thread(self._db.get_platinum_samples)

            # FR-EVO-02: Get error book samples with lower weight
            error_samples = []
            try:
                from services.error_book_sampler import ErrorBookSampler
                error_sampler = ErrorBookSampler(self.config)
                await error_sampler.initialize()
                error_samples = await error_sampler.collect_error_samples()
                logger.info(f"Collected {len(error_samples)} error book samples for retraining")
            except Exception as e:
                logger.warning(f"Failed to collect error book samples: {e}")

            if not silver_samples and not platinum_samples and not error_samples:
                logger.warning("No training samples available for retraining")
                return

            # Prepare training data with weighted samples
            train_data = self._prepare_training_data(silver_samples, platinum_samples, error_samples)

            # Train classifier
            classifier = Classifier()
            new_version = await classifier.retrain(train_data)

            if new_version:
                logger.info(f"Model retraining completed: new version {new_version}")

                # Update auto evolution status (P0-2: to_thread)
                await asyncio.to_thread(
                    self._db.update_auto_evolution_status,
                    {
                        'retrain_status': RetrainStatus.COMPLETED,
                        'current_model_version': new_version,
                        'last_retrain_at': datetime.utcnow().isoformat(),
                        'last_retrain_silver_total': snapshot_total,
                    }
                )
            else:
                logger.error("Model retraining failed")
                # IMPORTANT-fix #6 (2026-06-07): also persist
                # last_retrain_silver_total on failure, otherwise
                # check_and_trigger next tick will see the same delta
                # (essentially unchanged from this attempt) and fire
                # again. Persisting the snapshot means we wait for
                # ANOTHER full 1000-delta of new silver data before
                # retrying, which gives time for whatever broke
                # (LLM rate-limit, disk full, etc.) to clear.
                await asyncio.to_thread(
                    self._db.update_auto_evolution_status,
                    {
                        'retrain_status': RetrainStatus.FAILED,
                        'last_retrain_silver_total': snapshot_total,
                    }
                )

        except Exception as e:
            logger.error(f"Retrain error: {e}", exc_info=True)
            try:
                # IMPORTANT-fix #6: also write snapshot on unhandled
                # exception so we don't immediately retry on next tick.
                await asyncio.to_thread(
                    self._db.update_auto_evolution_status,
                    {
                        'retrain_status': RetrainStatus.FAILED,
                        'last_retrain_silver_total': snapshot_total,
                    }
                )
            except Exception:
                pass

    def _prepare_training_data(
        self,
        silver_samples: list,
        platinum_samples: list,
        error_samples: list
    ) -> Dict[str, Any]:
        """
        Prepare training data with weighted sample handling.

        Weight strategy:
        - platinum (manually verified): 3.0
        - silver (high-confidence auto-labeled): 1.0
        - error_book (LLM-judged hard examples): 0.5

        Returns:
            Dictionary with texts, labels, and weights for training
        """
        texts = []
        labels = []
        weights = []

        # Platinum samples (manually verified) - highest weight
        for sample in platinum_samples:
            texts.append(sample.get('cleaned_text', ''))
            labels.append(sample.get('correct_risk_label', sample.get('risk_label_level1', '未知')))
            weights.append(3.0)

        # Silver samples (high-confidence auto-labeled) - normal weight
        for sample in silver_samples:
            texts.append(sample.get('cleaned_text', ''))
            labels.append(sample.get('risk_label_level1', '未知'))
            weights.append(1.0)

        # Error book samples (LLM-judged hard examples) - lower weight
        for sample in error_samples:
            texts.append(sample.get('text', ''))
            labels.append(sample.get('label', '未知'))
            weights.append(sample.get('sample_weight', 0.5))

        return {
            'texts': texts,
            'labels': labels,
            'weights': weights
        }


# Database helper extensions
def extend_postgres_service():
    """Extend PostgreSQLService with retraining-related methods if not already present."""
    from services.database import PostgreSQLService
    from psycopg2 import sql

    # Check if method already exists
    if hasattr(PostgreSQLService, 'count_silver_samples'):
        return

    @staticmethod
    def count_silver_samples() -> int:
        """Count silver samples (high-confidence clues with positive feedback)."""
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT COUNT(*) as cnt FROM {}.clues c
                LEFT JOIN {}.feedback f ON c.clue_id = f.clue_id
                WHERE c.confidence >= 0.8 AND f.feedback_id IS NULL
            """).format(sql.Identifier(instance.schema), sql.Identifier(instance.schema)))
            return cur.fetchone()['cnt']

    @staticmethod
    def count_platinum_samples() -> int:
        """Count platinum samples (manually verified feedback)."""
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT COUNT(*) as cnt FROM {}.feedback
                WHERE platinum_enrolled = TRUE
            """).format(sql.Identifier(instance.schema)))
            return cur.fetchone()['cnt']

    @staticmethod
    def get_silver_samples(limit: int = 5000) -> list:
        """Get silver samples for training."""
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT c.clue_id, c.cleaned_text, c.risk_label_level1, c.confidence
                FROM {}.clues c
                LEFT JOIN {}.feedback f ON c.clue_id = f.clue_id
                WHERE c.confidence >= 0.8 AND f.feedback_id IS NULL
                LIMIT %(limit)s
            """).format(sql.Identifier(instance.schema), sql.Identifier(instance.schema)), {'limit': limit})
            return cur.fetchall()

    @staticmethod
    def get_platinum_samples(limit: int = 5000) -> list:
        """Get platinum samples for training."""
        instance = PostgreSQLService.get_instance()

        with instance._get_cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT c.clue_id, c.cleaned_text, f.correct_risk_label_level1 as correct_risk_label
                FROM {}.clues c
                JOIN {}.feedback f ON c.clue_id = f.clue_id
                WHERE f.platinum_enrolled = TRUE
                LIMIT %(limit)s
            """).format(sql.Identifier(instance.schema), sql.Identifier(instance.schema)), {'limit': limit})
            return cur.fetchall()

    # Attach methods to class
    PostgreSQLService.count_silver_samples = count_silver_samples
    PostgreSQLService.count_platinum_samples = count_platinum_samples
    PostgreSQLService.get_silver_samples = get_silver_samples
    PostgreSQLService.get_platinum_samples = get_platinum_samples