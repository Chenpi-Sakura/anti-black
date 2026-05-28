"""
Telegram Collector - Telethon 被动监听采集器
使用 events.NewMessage 异步事件源被动收集 Telegram 消息
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError

from config import get_config
from services.database import PostgreSQLService
from services.telegram_session_manager import TelegramSessionManager

logger = logging.getLogger(__name__)


class TelegramCollector:
    """
    Telegram 被动监听采集器。

    核心设计：
    - 重被动监听，轻主动请求
    - 单账号作为"安静的潜水员"
    - 通过 events.NewMessage 异步事件源收集增量数据
    """

    def __init__(
        self,
        session_manager: TelegramSessionManager,
        config: Optional[Dict[str, Any]] = None
    ):
        self.session_manager = session_manager
        self.config = config or get_config()
        self._client: Optional[TelegramClient] = None
        self._running = False
        self._db: Optional[PostgreSQLService] = None
        self._keywords: List[Dict[str, str]] = []
        self._channel_id_to_db_id: Dict[int, int] = {}  # Telegram channel_id -> DB channel id

    async def initialize(self) -> None:
        """初始化组件。"""
        self._db = PostgreSQLService.get_instance()
        await self._load_keywords()
        await self._build_channel_map()

    async def _load_keywords(self) -> None:
        """从数据库加载关键词（支持正则）。"""
        if not self._db:
            return

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    SELECT id, keyword, regex_pattern
                    FROM telegram.telegram_keyword
                    WHERE is_enabled = TRUE
                """)
                self._keywords = [
                    {'id': row['id'], 'keyword': row['keyword'], 'regex': row['regex_pattern']}
                    for row in cur.fetchall()
                ]
                logger.info(f"Loaded {len(self._keywords)} keywords")
        except Exception as e:
            logger.error(f"Failed to load keywords: {e}")

    async def _build_channel_map(self) -> None:
        """构建 Telegram channel_id 到数据库 ID 的映射。"""
        if not self._db:
            return

        try:
            with self._db._get_cursor() as cur:
                cur.execute("SELECT id, channel_id FROM telegram.telegram_channel")
                self._channel_id_to_db_id = {
                    row['channel_id']: row['id'] for row in cur.fetchall()
                }
        except Exception as e:
            logger.error(f"Failed to build channel map: {e}")

    async def start(self, account_id: int = 1) -> bool:
        """
        启动采集器 - 被动监听消息事件。

        Args:
            account_id: Telegram 账号 ID

        Returns:
            是否启动成功
        """
        if self._running:
            logger.warning("Collector already running")
            return True

        # 初始化
        await self.initialize()

        # 启动 client
        success = await self.session_manager.start_client(account_id)
        if not success:
            logger.error("Failed to start Telegram client")
            return False

        self._client = self.session_manager.get_client(account_id)
        if not self._client:
            logger.error("Client not available")
            return False

        self._running = True

        # 注册事件处理器
        self._client.add_event_handler(
            self._on_new_message,
            events.NewMessage(incoming=True)
        )

        logger.info("Telegram collector started, listening for messages...")
        return True

    async def stop(self) -> None:
        """停止采集器。"""
        if not self._running:
            return

        self._running = False

        if self._client:
            # 移除事件处理器
            self._client.remove_event_handler(self._on_new_message)
            await self._client.disconnect()

        logger.info("Telegram collector stopped")

    @events.register
    async def _on_new_message(self, event: events.NewMessage) -> None:
        """
        轻量级回调 - 仅收集消息元数据，丢入后台任务处理。

        重要：不阻塞事件循环，耗时的 DB 写入用 create_task 丢到后台。
        """
        # 忽略自己发送的消息
        if event.outgoing:
            return

        # 异步处理消息
        asyncio.create_task(self._process_message(event))

    async def _process_message(self, event: events.NewMessage) -> None:
        """
        耗时处理：正则匹配、写入 PostgreSQL。

        全局捕获 FloodWaitError 等异常。
        """
        try:
            # 获取消息信息
            message = event.message
            chat = await event.get_chat()

            # 获取 channel_id (可能为负数 for private groups)
            channel_id = chat.id if hasattr(chat, 'id') else message.peer_id.channel_id

            # 获取数据库中的 channel id
            db_channel_id = self._channel_id_to_db_id.get(channel_id)
            if not db_channel_id:
                logger.debug(f"Channel {channel_id} not in monitor list, skipping")
                return

            # 获取用户信息
            user_id = message.sender_id
            username = None
            if hasattr(message.sender, 'username') and message.sender.username:
                username = message.sender.username

            # 获取文本
            text = message.text or message.message or ""

            if not text.strip():
                return

            # 关键词匹配
            matched_keyword_id = None
            for kw in self._keywords:
                try:
                    if re.search(kw['regex'], text, re.IGNORECASE):
                        matched_keyword_id = kw['id']
                        break
                except re.error as e:
                    logger.warning(f"Invalid regex '{kw['regex']}': {e}")

            # 写入数据库
            await self._save_message(
                message_id=message.id,
                channel_id=db_channel_id,
                user_id=user_id,
                username=username,
                text=text,
                timestamp=message.date,
                matched_keyword_id=matched_keyword_id,
                raw_json=message.to_dict()
            )

            logger.debug(f"Saved message {message.id} from channel {channel_id}")

        except FloodWaitError as e:
            # FloodWait 全局处理：严格等待 e.seconds × 2
            wait_time = e.seconds * 2
            logger.warning(f"FloodWait: sleeping {wait_time}s")
            await asyncio.sleep(wait_time)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    async def _save_message(
        self,
        message_id: int,
        channel_id: int,
        user_id: Optional[int],
        username: Optional[str],
        text: str,
        timestamp: datetime,
        matched_keyword_id: Optional[int],
        raw_json: Dict[str, Any]
    ) -> None:
        """将消息写入 PostgreSQL。"""
        if not self._db:
            self._db = PostgreSQLService.get_instance()

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO telegram.telegram_message
                        (message_id, channel_id, user_id, username, text, timestamp,
                         matched_keyword_id, raw_json, processed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                    ON CONFLICT (channel_id, message_id) DO NOTHING
                """, (
                    message_id, channel_id, user_id, username, text, timestamp,
                    matched_keyword_id, Json(raw_json)
                ))
        except Exception as e:
            logger.error(f"Failed to save message: {e}")

    async def health_check(self) -> bool:
        """检查采集器健康状态。"""
        if not self._client or not self._running:
            return False

        try:
            # 尝试获取 me 信息
            me = await self._client.get_me()
            return me is not None
        except Exception:
            return False

    def get_listening_channels(self) -> List[int]:
        """获取当前监听的频道 ID 列表。"""
        return list(self._channel_id_to_db_id.keys())