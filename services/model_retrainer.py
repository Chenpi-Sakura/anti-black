"""
Model Retrainer - FR-EVO-03
Checks sample counts and triggers model retraining when threshold is reached.
"""
import asyncio
import logging
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

    async def initialize(self):
        """Initialize database connection."""
        self._db = PostgreSQLService.get_instance()

    async def check_and_trigger(self) -> bool:
        """
        Check if retraining threshold is reached and trigger if so.

        Returns:
            True if retraining was triggered, False otherwise
        """
        if not self._db:
            await self.initialize()

        threshold = self.config.get('auto_evolution', {}).get('retrain', {}).get('trigger_threshold', 2000)

        # Get dynamic counts
        silver_count = self._db.count_silver_samples()
        platinum_count = self._db.count_platinum_samples()
        total = silver_count + platinum_count

        logger.info(f"Retrain check: silver={silver_count}, platinum={platinum_count}, total={total}, threshold={threshold}")

        if total < threshold:
            return False

        # Threshold reached - trigger retraining
        logger.info(f"Retrain threshold reached: {total} samples, triggering retrain")

        # Update status to QUEUED
        self._db.update_auto_evolution_status({
            'retrain_status': RetrainStatus.QUEUED
        })

        # Trigger async retraining (non-blocking)
        asyncio.create_task(self._run_retrain())

        return True

    async def _run_retrain(self):
        """
        Execute model retraining pipeline.

        This runs asynchronously and doesn't block the daemon.
        """
        try:
            logger.info("Starting model retraining...")

            # Import retrain components
            from pipeline.classifier import Classifier
            from models import Feedback

            # Get training data
            silver_samples = self._db.get_silver_samples()
            platinum_samples = self._db.get_platinum_samples()

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

                # Update auto evolution status
                self._db.update_auto_evolution_status({
                    'retrain_status': RetrainStatus.COMPLETED,
                    'current_model_version': new_version,
                    'last_retrain_at': asyncio.get_event_loop().time()
                })
            else:
                logger.error("Model retraining failed")
                self._db.update_auto_evolution_status({
                    'retrain_status': RetrainStatus.FAILED
                })

        except Exception as e:
            logger.error(f"Retrain error: {e}", exc_info=True)
            self._db.update_auto_evolution_status({
                'retrain_status': RetrainStatus.FAILED
            })

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