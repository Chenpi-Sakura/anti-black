"""
Collection module for AntiBlack pipeline.
Handles data collection from various sources.
"""
import logging
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CollectionMessage:
    """Raw message from collection."""

    def __init__(
        self,
        message_id: str,
        source_channel: str,
        group_id: str,
        author_id: str,
        raw_text: str,
        published_at: str,
        metadata: Dict[str, Any] = None
    ):
        self.message_id = message_id
        self.source_channel = source_channel
        self.group_id = group_id
        self.author_id = author_id
        self.raw_text = raw_text
        self.published_at = published_at
        self.metadata = metadata or {}


class BaseCollector(ABC):
    """Base collector interface."""

    @abstractmethod
    async def collect(self, keywords: List[str], time_range: Dict[str, str]) -> List[CollectionMessage]:
        """Collect messages matching criteria."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check collector health."""
        pass


class TelegramCollector(BaseCollector):
    """
    Telegram collector implementation using Telethon passive listening.

    Note: This collector is event-based (long-running), not polling-based.
    The actual integration is done via services.telegram_collector.TelegramCollector
    which is started by the daemon scheduler.

    This class provides backward compatibility with the Collector interface
    but actual message collection happens through the passive listener.
    """

    def __init__(self, bot_token: str = None, chat_ids: List[str] = None, keywords: List[str] = None):
        # Note: bot_token is not used in new implementation (MTProto uses api_id/api_hash)
        self.bot_token = bot_token
        self.chat_ids = chat_ids or []
        self.keywords = keywords or []
        self._collector = None
        self._session_manager = None

    async def collect(self, keywords: List[str], time_range: Dict[str, str]) -> List[CollectionMessage]:
        """
        This method is not used in the new implementation.
        Actual collection is done via passive event listening in services.telegram_collector.
        Returns empty list as messages come through the event handler.
        """
        # The new architecture uses events.NewMessage passive listening
        # Messages are processed asynchronously and stored directly to DB
        # This method exists only for interface compatibility
        return []

    async def health_check(self) -> bool:
        """Check if the Telegram collector is running."""
        if self._collector:
            return await self._collector.health_check()
        return False

    async def start(self, account_id: int = 1) -> bool:
        """Start the passive listener."""
        try:
            from services.telegram_session_manager import TelegramSessionManager
            from services.telegram_collector import TelegramCollector as NewTelegramCollector

            self._session_manager = TelegramSessionManager()
            self._collector = NewTelegramCollector(self._session_manager)
            return await self._collector.start(account_id)
        except Exception as e:
            logger.error(f"Failed to start Telegram collector: {e}")
            return False

    async def stop(self) -> None:
        """Stop the passive listener."""
        if self._collector:
            await self._collector.stop()


class ForumCollector(BaseCollector):
    """Forum/贴吧 collector implementation."""

    def __init__(self, forum_urls: List[str], keywords: List[str] = None):
        self.forum_urls = forum_urls
        self.keywords = keywords or []

    async def collect(self, keywords: List[str], time_range: Dict[str, str]) -> List[CollectionMessage]:
        """Collect messages from forums."""
        messages = []

        # Mock collection for demo
        for url in self.forum_urls:
            mock_msg = CollectionMessage(
                message_id=f"msg_forum_{len(messages)}",
                source_channel="baidu_tieba",
                group_id=url,
                author_id="forum_user_001",
                raw_text="贴吧看到的出号信息，抖音号，有需要的加V",
                published_at="2026-05-23T09:30:00+08:00"
            )
            messages.append(mock_msg)

        return messages

    async def health_check(self) -> bool:
        """Check forum collector health."""
        return True


class Collector:
    """Main collector coordinator."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.collectors: Dict[str, BaseCollector] = {}
        self._init_collectors()

    def _init_collectors(self) -> None:
        """Initialize configured collectors."""
        # Telegram
        telegram_config = self.config.get('telegram', {})
        if telegram_config.get('enabled'):
            self.collectors['telegram'] = TelegramCollector(
                bot_token=telegram_config.get('bot_token', ''),
                chat_ids=telegram_config.get('chat_ids', []),
                keywords=telegram_config.get('keywords', [])
            )

        # Forum
        forum_config = self.config.get('forum', {})
        if forum_config.get('enabled'):
            self.collectors['forum'] = ForumCollector(
                forum_urls=forum_config.get('urls', []),
                keywords=forum_config.get('keywords', [])
            )

    async def collect_from_channel(
        self,
        channel: str,
        keywords: List[str],
        time_range: Dict[str, str]
    ) -> List[CollectionMessage]:
        """Collect from a specific channel."""
        collector = self.collectors.get(channel)
        if not collector:
            logger.warning(f"No collector for channel: {channel}")
            return []

        try:
            return await collector.collect(keywords, time_range)
        except Exception as e:
            logger.error(f"Error collecting from {channel}: {e}")
            return []

    async def collect_all(
        self,
        keywords: List[str],
        time_range: Dict[str, str],
        channels: List[str] = None
    ) -> List[CollectionMessage]:
        """Collect from all or specified channels."""
        all_messages = []
        target_channels = channels or list(self.collectors.keys())

        for channel in target_channels:
            messages = await self.collect_from_channel(channel, keywords, time_range)
            all_messages.extend(messages)

        return all_messages

    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all collectors."""
        results = {}
        for channel, collector in self.collectors.items():
            try:
                results[channel] = await collector.health_check()
            except Exception:
                results[channel] = False
        return results