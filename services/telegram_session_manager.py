"""
Telegram Session Manager - StringSession 持久化管理
将 Telethon 的 StringSession 存储到 PostgreSQL telegram schema
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import get_config
from services.database import PostgreSQLService

logger = logging.getLogger(__name__)


class TelegramSessionManager:
    """
    管理 Telegram 账号的 StringSession 持久化。

    使用 PostgreSQL 的 telegram schema 存储会话数据，
    支持多账号管理（当前为单账号架构）。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or get_config()
        self._db: Optional[PostgreSQLService] = None
        self._clients: Dict[int, TelegramClient] = {}  # account_id -> client

    async def initialize(self) -> None:
        """初始化数据库连接。"""
        self._db = PostgreSQLService.get_instance()

    async def load_session(self, account_id: int) -> Optional[str]:
        """
        从 PostgreSQL 加载 StringSession。

        Args:
            account_id: Telegram 账号 ID

        Returns:
            StringSession 字符串，如果不存在则返回 None
        """
        if not self._db:
            await self.initialize()

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    SELECT string_session
                    FROM telegram.telegram_account
                    WHERE account_id = %s AND is_enabled = TRUE
                """, (account_id,))
                result = cur.fetchone()
                if result and result.get('string_session'):
                    logger.info(f"Loaded session for account {account_id}")
                    return result['string_session']
                logger.warning(f"No session found for account {account_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to load session for account {account_id}: {e}")
            return None

    async def save_session(self, account_id: int, string_session: str) -> bool:
        """
        将 StringSession 写入 PostgreSQL。

        Args:
            account_id: Telegram 账号 ID
            string_session: StringSession 字符串

        Returns:
            是否保存成功
        """
        if not self._db:
            await self.initialize()

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO telegram.telegram_account
                        (account_id, string_session, modified_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (account_id)
                    DO UPDATE SET
                        string_session = EXCLUDED.string_session,
                        modified_at = NOW()
                """, (account_id, string_session))
                logger.info(f"Saved session for account {account_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to save session for account {account_id}: {e}")
            return False

    async def get_account_info(self, account_id: int) -> Optional[Dict[str, Any]]:
        """
        获取账号信息。

        Returns:
            账号信息字典，包含 api_id, api_hash, phone 等
        """
        if not self._db:
            await self.initialize()

        try:
            with self._db._get_cursor() as cur:
                cur.execute("""
                    SELECT account_id, api_id, api_hash, phone, is_enabled, created_at
                    FROM telegram.telegram_account
                    WHERE account_id = %s
                """, (account_id,))
                result = cur.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get account info for {account_id}: {e}")
            return None

    async def create_client(self, account_id: int) -> Optional[TelegramClient]:
        """
        创建已绑定 StringSession 的 TelegramClient。

        Args:
            account_id: Telegram 账号 ID

        Returns:
            TelegramClient 实例，失败返回 None
        """
        account_info = await self.get_account_info(account_id)
        if not account_info:
            logger.error(f"Account {account_id} not found in database")
            return None

        # 获取配置
        telegram_config = self.config.get('telegram', {})
        api_id = account_info.get('api_id') or telegram_config.get('api_id')
        api_hash = account_info.get('api_hash') or telegram_config.get('api_hash')

        if not api_id or not api_hash:
            logger.error(f"API credentials not configured for account {account_id}")
            return None

        # 加载 session
        string_session = await self.load_session(account_id)

        # 创建 client
        session = StringSession(string_session) if string_session else StringSession()

        client = TelegramClient(
            session,
            api_id,
            api_hash,
            device_model="iPhone 13 Pro",
            system_version="15.0",
            app_version="8.4",
            flood_sleep_threshold=0  # 全局禁用 flood sleep我们自己处理
        )

        # 缓存 client
        self._clients[account_id] = client
        logger.info(f"Created TelegramClient for account {account_id}")

        return client

    async def start_client(self, account_id: int) -> bool:
        """
        启动 TelegramClient 并确保已认证。

        如果没有 session，会提示用户输入验证码。

        Args:
            account_id: Telegram 账号 ID

        Returns:
            是否启动成功
        """
        client = await self.create_client(account_id)
        if not client:
            return False

        try:
            await client.start()

            # 如果是首次认证（没有 string_session），保存 session
            if not await self.load_session(account_id):
                session_str = client.session.save()
                await self.save_session(account_id, session_str)
                logger.info(f"New session saved for account {account_id}")

            return True
        except Exception as e:
            logger.error(f"Failed to start client for account {account_id}: {e}")
            return False

    async def stop_client(self, account_id: int) -> None:
        """停止指定的 TelegramClient。"""
        client = self._clients.get(account_id)
        if client:
            await client.disconnect()
            del self._clients[account_id]
            logger.info(f"Stopped client for account {account_id}")

    async def stop_all(self) -> None:
        """停止所有 TelegramClient。"""
        for account_id in list(self._clients.keys()):
            await self.stop_client(account_id)

    def get_client(self, account_id: int) -> Optional[TelegramClient]:
        """获取已缓存的 TelegramClient。"""
        return self._clients.get(account_id)