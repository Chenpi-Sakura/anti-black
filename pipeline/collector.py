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
    """Telegram collector implementation."""

    def __init__(self, bot_token: str, chat_ids: List[str], keywords: List[str] = None):
        self.bot_token = bot_token
        self.chat_ids = chat_ids
        self.keywords = keywords or []
        self.api_base = f"https://api.telegram.org/bot{bot_token}"

    async def collect(self, keywords: List[str], time_range: Dict[str, str]) -> List[CollectionMessage]:
        """Collect messages from Telegram."""
        messages = []

        # In demo mode, generate mock data
        # In production, integrate with Telegram API
        for chat_id in self.chat_ids:
            try:
                # Mock collection for demo
                mock_msg = CollectionMessage(
                    message_id=f"msg_{chat_id}_{len(messages)}",
                    source_channel="telegram",
                    group_id=chat_id,
                    author_id="user_001",
                    raw_text=self._generate_mock_text(keywords),
                    published_at="2026-05-23T10:00:00+08:00"
                )
                messages.append(mock_msg)
            except Exception as e:
                logger.error(f"Error collecting from {chat_id}: {e}")

        return messages

    async def health_check(self) -> bool:
        """Check Telegram API health."""
        # In production, make a test API call
        return True

    def _generate_mock_text(self, keywords: List[str]) -> str:
        """Generate mock message text."""
        templates = [
            "出抖号，千粉，换绑稳，加V:dyhao668",
            "接码平台上线了新服务，联系Q:123456",
            "专业刷粉，1000粉只需80元，微信:brushdan",
            "大量抖音号出售，感兴趣的加微信号dy666888"
        ]
        return templates[hash(keywords[0] if keywords else "default") % len(templates)]


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