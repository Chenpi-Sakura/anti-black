"""
Telegram Pipeline Task - 将 Telegram 消息定时推入黑话学习 pipeline
定时扫描未处理消息 → 调用 SlangLearner.process_text() → 更新 processed=true
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List

from psycopg2 import sql
from psycopg2.extras import Json

from config import get_config
from services.database import PostgreSQLService

logger = logging.getLogger(__name__)


class TelegramPipelineTask:
    """
    定时任务：扫描未处理消息 → 推入 SlangLearner。

    工作流程：
    1. 扫描 telegram.telegram_message WHERE processed=false
    2. 调用 SlangLearner.process_text(text)
    3. 更新 processed=true
    4. 记录 clue_id 关联到 antiblack.clues
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or get_config()
        self._db: Optional[PostgreSQLService] = None
        self._slang_learner = None
        self._batch_size: int = 100

    async def initialize(self) -> None:
        """初始化组件。"""
        self._db = PostgreSQLService.get_instance()
        self._batch_size = self.config.get('telegram', {}).get('pipeline_batch_size', 100)

    async def _load_slang_learner(self):
        """延迟加载 SlangLearner 以避免循环导入。"""
        if self._slang_learner is None:
            from pipeline.slang_learning import SlangLearner
            self._slang_learner = SlangLearner(self.config)
            await self._slang_learner.initialize()
            logger.info("SlangLearner loaded for Telegram pipeline")

    async def run(self) -> int:
        """
        执行一次 pipeline 处理。

        Returns:
            处理的消息数量
        """
        if not self._db:
            await self.initialize()

        # 确保 SlangLearner 已加载
        await self._load_slang_learner()

        # 使用 FOR UPDATE SKIP LOCKED 安全获取未处理消息
        messages = await self._fetch_unprocessed_messages(self._batch_size)
        if not messages:
            return 0

        logger.info(f"Telegram pipeline: processing {len(messages)} messages")

        processed_count = 0
        for msg in messages:
            try:
                clue_id = await self._process_message(msg)
                await self._mark_processed(msg['id'], clue_id)
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to process message {msg['id']}: {e}")
                # 标记为 processed 以避免无限重试
                await self._mark_processed(msg['id'], None, failed=True)

        logger.info(f"Telegram pipeline: processed {processed_count}/{len(messages)} messages")
        return processed_count

    async def _fetch_unprocessed_messages(self, batch_size: int) -> List[Dict[str, Any]]:
        """
        使用行级锁安全获取未处理消息，避免重复处理。

        使用 UPDATE ... RETURNING 语法，拉取时立即将记录标记为 in_progress。
        """
        try:
            with self._db._get_cursor() as cur:
                # PostgreSQL 的 UPDATE ... RETURNING ... WHERE ... FOR UPDATE SKIP LOCKED
                cur.execute("""
                    UPDATE telegram.telegram_message
                    SET raw_json = raw_json || '{"processed": "in_progress"}'::jsonb
                    WHERE id IN (
                        SELECT id FROM telegram.telegram_message
                        WHERE (raw_json->>'processed') IS NULL
                           OR (raw_json->>'processed') = 'false'
                        ORDER BY created_at ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, message_id, channel_id, user_id, username,
                              text, timestamp, matched_keyword_id, raw_json
                """, (batch_size,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Failed to fetch unprocessed messages: {e}")
            return []

    async def _process_message(self, msg: Dict[str, Any]) -> Optional[str]:
        """
        处理单条消息，调用 SlangLearner。

        Returns:
            clue_id 如果成功，否则 None
        """
        text = msg.get('text', '')
        if not text.strip():
            return None

        # 调用 SlangLearner.process_text()
        try:
            result = await self._slang_learner.process_text(
                text=text,
                source_channel='telegram',
                source_group_id=str(msg.get('channel_id', '')),
                source_author_id=str(msg.get('user_id', '')) if msg.get('user_id') else None
            )
            return result
        except Exception as e:
            logger.error(f"SlangLearner.process_text failed: {e}")
            return None

    async def _mark_processed(
        self,
        msg_db_id: int,
        clue_id: Optional[str],
        failed: bool = False
    ) -> None:
        """标记消息为已处理。"""
        try:
            with self._db._get_cursor() as cur:
                # 更新 processed 字段
                processed_value = 'failed' if failed else 'true'
                update_fields = {
                    'processed': processed_value,
                    'raw_json': sql.SQL("raw_json || %s")
                }
                params = [
                    Json({'processed': processed_value, 'clue_id': clue_id}),
                    msg_db_id
                ]

                cur.execute("""
                    UPDATE telegram.telegram_message
                    SET raw_json = raw_json || %s
                    WHERE id = %s
                """, params)

        except Exception as e:
            logger.error(f"Failed to mark message {msg_db_id} as processed: {e}")

    async def run_loop(self, interval_seconds: int = 300) -> None:
        """
        持续运行循环。

        Args:
            interval_seconds: 每次运行之间的间隔（默认5分钟）
        """
        logger.info(f"Telegram pipeline loop started (interval={interval_seconds}s)")

        while True:
            try:
                await self.run()
            except Exception as e:
                logger.error(f"Telegram pipeline error: {e}", exc_info=True)

            await asyncio.sleep(interval_seconds)

    def get_stats(self) -> Dict[str, int]:
        """获取处理统计。"""
        if not self._db:
            return {'pending': 0, 'processed': 0, 'in_progress': 0, 'failed': 0}

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE raw_json->>'processed' IS NULL
                                         OR raw_json->>'processed' = 'false') as pending,
                        COUNT(*) FILTER (WHERE raw_json->>'processed' = 'true') as processed,
                        COUNT(*) FILTER (WHERE raw_json->>'processed' = 'in_progress') as in_progress,
                        COUNT(*) FILTER (WHERE raw_json->>'processed' = 'failed') as failed
                    FROM telegram.telegram_message
                """)
                result = cur.fetchone()
                return dict(result) if result else {'pending': 0, 'processed': 0, 'in_progress': 0, 'failed': 0}
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {'pending': 0, 'processed': 0, 'in_progress': 0, 'failed': 0}