"""
MediaCrawler Adapter for AntiBlack pipeline.
Polls MediaCrawler PostgreSQL database for new content and feeds into AntiBlack pipeline.
Uses SlangMapping (confirmed slang) as keywords for content filtering.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class MediaCrawlerAdapter:
    """
    Adapter that bridges MediaCrawler storage to AntiBlack pipeline.
    Polls MediaCrawler PostgreSQL database for new content.
    Uses SlangMapping (confirmed slang) as采集关键词.
    """
    MIN_DATETIME = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._db_pool: Optional[asyncpg.Pool] = None
        self._last_check_time: Dict[str, datetime] = {}
        self._keywords: List[str] = []
        self._mongo_db = None

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        mc_config = self.config.get('media_crawler', {})
        db_config = mc_config.get('database', {})

        self._db_pool = await asyncpg.create_pool(
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            user=db_config.get('user', 'antiblack'),
            password=db_config.get('password', 'antiblack123'),
            database=db_config.get('database', 'antiblack'),
            min_size=2,
            max_size=5
        )

        # Initialize PostgreSQL connection for reading SlangMapping
        from services.database import PostgreSQLService
        self._pg_db = PostgreSQLService.get_instance()

        logger.info("MediaCrawler adapter initialized")

    async def finalize(self) -> None:
        """Close database connection pool."""
        if self._db_pool:
            await self._db_pool.close()
            self._db_pool = None

    async def sync_keywords_from_slang_mapping(self) -> List[str]:
        """
        Sync keywords from SlangMapping (confirmed slang).
        黑话 = 关键词，从PostgreSQL读取已确认的黑话作为采集关键词。
        """
        if not self._pg_db:
            self._pg_db = PostgreSQLService.get_instance()

        try:
            # Read all verified (CONFIRMED) slang mappings
            slang_mappings = self._pg_db.get_all_slang_mappings(verified_only=True)
            keywords = [m['slang_raw'] for m in slang_mappings if m.get('slang_raw')]

            if keywords:
                old_keywords = self._keywords
                self._keywords = keywords
                logger.info(f"Synced {len(keywords)} keywords from SlangMapping: {keywords[:5]}...")
                if set(old_keywords) != set(keywords):
                    logger.info(f"Keywords updated: added {set(keywords) - set(old_keywords)}, removed {set(old_keywords) - set(keywords)}")
            else:
                # Fallback to default keywords if SlangMapping is empty
                self._keywords = ['出抖号', '抖音号买卖', '加V', '千粉', '微信号', '加微', '刷粉']
                logger.warning(f"SlangMapping empty, using default keywords: {self._keywords}")

            return self._keywords
        except Exception as e:
            logger.error(f"Failed to sync keywords from SlangMapping: {e}")
            # Fallback to default keywords
            self._keywords = ['出抖号', '抖音号买卖', '加V', '千粉', '微信号', '加微', '刷粉']
            return self._keywords

    async def poll_new_content(self, platform: str) -> List[Dict[str, Any]]:
        """
        Poll new content from MediaCrawler database.
        Filters content based on keywords from SlangMapping.

        Args:
            platform: 'douyin' or 'tieba'

        Returns:
            List of RawMessage-formatted content items
        """
        if not self._db_pool:
            await self.initialize()

        # Sync keywords before polling
        await self.sync_keywords_from_slang_mapping()

        if platform == 'douyin':
            return await self._poll_douyin()
        elif platform == 'tieba':
            return await self._poll_tieba()
        elif platform == 'xhs':
            return await self._poll_xhs()
        elif platform == 'ks':
            return await self._poll_kuaishou()
        elif platform == 'weibo':
            return await self._poll_weibo()
        else:
            logger.warning(f"Unsupported platform: {platform}")
            return []

    def _build_keyword_filter(self, text_column: str = 'title') -> str:
        """
        Build SQL ILIKE filter for keywords.
        Returns SQL condition like: (title ILIKE '%出抖号%' OR title ILIKE '%加V%' OR ...)
        """
        if not self._keywords:
            return "1=1"  # No filter if no keywords

        # Quote reserved words like 'desc'
        col = f'"{text_column}"' if text_column.lower() in ('desc', 'content') else text_column
        conditions = [f"({col} ILIKE '%{kw}%')" for kw in self._keywords]
        return f"({' OR '.join(conditions)})"

    async def _poll_douyin(self) -> List[Dict[str, Any]]:
        """Poll new Douyin content, filtered by keywords from SlangMapping."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter = self._build_keyword_filter('title')

                query = f"""
                    SELECT
                        aweme_id,
                        title,
                        "desc",
                        nickname,
                        user_unique_id,
                        create_time,
                        liked_count,
                        comment_count,
                        ip_location,
                        aweme_url,
                        source_keyword,
                        add_ts,
                        last_modify_ts
                    FROM public.douyin_aweme
                    WHERE add_ts > $1 AND ({keyword_filter})
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts = self._last_check_time.get('douyin', self.MIN_DATETIME).timestamp()
                rows = await conn.fetch(query, last_ts)

                if rows:
                    self._last_check_time['douyin'] = datetime.now()
                    logger.info(f"Polled {len(rows)} new Douyin videos (keyword filter: {len(self._keywords)} keywords)")

                return [self._convert_douyin_video(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"douyin poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_douyin_video(row) for row in rows]
            logger.error(f"douyin poll failed: {e}")
            return []

    async def _poll_tieba(self) -> List[Dict[str, Any]]:
        """Poll new Tieba content, filtered by keywords from SlangMapping."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                # Build keyword filter - check both title and desc
                keyword_filter_title = self._build_keyword_filter('title')
                keyword_filter_content = self._build_keyword_filter('desc')
                combined_filter = f"({keyword_filter_title} OR {keyword_filter_content})"

                # last_modify_ts is millisecond timestamp, add_ts is NULL for all records
                last_ts = self._last_check_time.get('tieba', self.MIN_DATETIME).timestamp()
                last_ts_ms = last_ts * 1000

                query = """
                    SELECT
                        note_id,
                        title,
                        "desc",
                        user_nickname,
                        ip_location,
                        total_replay_num,
                        source_keyword,
                        add_ts,
                        last_modify_ts
                    FROM public.tieba_note
                    WHERE (add_ts IS NOT NULL AND add_ts > $1)
                       OR (add_ts IS NULL AND last_modify_ts > $2)
                    ORDER BY COALESCE(add_ts, (last_modify_ts / 1000)::timestamp) ASC
                    LIMIT 100
                """

                rows = await conn.fetch(query, last_ts, last_ts_ms)

                if rows:
                    self._last_check_time['tieba'] = datetime.now()
                    logger.info(f"Polled {len(rows)} new Tieba posts (keyword filter: {len(self._keywords)} keywords)")

                return [self._convert_tieba_post(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"tieba poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_tieba_post(row) for row in rows]
            logger.error(f"tieba poll failed: {e}")
            return []

    def _convert_douyin_video(self, row) -> Dict[str, Any]:
        """Convert Douyin video to RawMessage format."""
        # Parse timestamp
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"dy_{row.get('aweme_id')}",
            "source_channel": "douyin",
            "group_id": row.get('source_keyword', ''),
            "author_id": str(row.get('user_unique_id', '')),
            "raw_text": f"{row.get('title', '')} {row.get('desc', '')}".strip(),
            "published_at": published_at,
            "metadata": {
                "platform": "douyin",
                "content_type": "video",
                "author": row.get('nickname', ''),
                "aweme_id": str(row.get('aweme_id', '')),
                "aweme_url": row.get('aweme_url', ''),
                "liked_count": row.get('liked_count', '0'),
                "comment_count": row.get('comment_count', '0'),
                "ip_location": row.get('ip_location', ''),
                "source_keyword": row.get('source_keyword', ''),
            }
        }

    def _convert_tieba_post(self, row) -> Dict[str, Any]:
        """Convert Tieba post to RawMessage format."""
        # Parse timestamp
        publish_time = row.get('publish_time', 0)
        if isinstance(publish_time, int):
            published_at = datetime.fromtimestamp(publish_time).isoformat()
        else:
            published_at = str(publish_time)

        return {
            "message_id": f"tieba_{row.get('note_id')}",
            "source_channel": "baidu_tieba",
            "group_id": row.get('source_keyword', ''),
            "author_id": str(row.get('user_nickname', '')),
            "raw_text": f"{row.get('title', '')} {row.get('desc', '')}".strip(),
            "published_at": published_at,
            "metadata": {
                "platform": "baidu_tieba",
                "content_type": "post",
                "note_id": str(row.get('note_id', '')),
                "title": row.get('title', ''),
                "author": row.get('user_nickname', ''),
                "reply_num": row.get('total_replay_num', '0'),
                "ip_location": row.get('ip_location', ''),
                "source_keyword": row.get('source_keyword', ''),
            }
        }

    async def _poll_xhs(self) -> List[Dict[str, Any]]:
        """Poll new Xiaohongshu content, filtered by keywords from SlangMapping."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter_title = self._build_keyword_filter('title')
                keyword_filter_desc = self._build_keyword_filter('desc')
                combined_filter = f"({keyword_filter_title} OR {keyword_filter_desc})"

                query = f"""
                    SELECT
                        note_id,
                        title,
                        "desc",
                        nickname,
                        user_id,
                        avatar,
                        ip_location,
                        liked_count,
                        collected_count,
                        comment_count,
                        share_count,
                        time,
                        note_url,
                        source_keyword,
                        add_ts,
                        last_modify_ts
                    FROM public.xhs_note
                    WHERE add_ts > $1 AND ({combined_filter})
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts = self._last_check_time.get('xhs', self.MIN_DATETIME).timestamp()
                rows = await conn.fetch(query, last_ts)

                if rows:
                    self._last_check_time['xhs'] = datetime.now()
                    logger.info(f"Polled {len(rows)} new Xiaohongshu notes (keyword filter: {len(self._keywords)} keywords)")

                return [self._convert_xhs_note(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"xhs poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_xhs_note(row) for row in rows]
            logger.error(f"xhs poll failed: {e}")
            return []

    def _convert_xhs_note(self, row) -> Dict[str, Any]:
        """Convert Xiaohongshu note to RawMessage format."""
        time_val = row.get('time', 0)
        if isinstance(time_val, int):
            published_at = datetime.fromtimestamp(time_val).isoformat()
        else:
            published_at = str(time_val)

        return {
            "message_id": f"xhs_{row.get('note_id')}",
            "source_channel": "xiaohongshu",
            "group_id": row.get('source_keyword', ''),
            "author_id": str(row.get('user_id', '')),
            "raw_text": f"{row.get('title', '')} {row.get('desc', '')}".strip(),
            "published_at": published_at,
            "metadata": {
                "platform": "xiaohongshu",
                "content_type": "note",
                "note_id": str(row.get('note_id', '')),
                "title": row.get('title', ''),
                "author": row.get('nickname', ''),
                "liked_count": row.get('liked_count', '0'),
                "collected_count": row.get('collected_count', '0'),
                "comment_count": row.get('comment_count', '0'),
                "share_count": row.get('share_count', '0'),
                "ip_location": row.get('ip_location', ''),
                "source_keyword": row.get('source_keyword', ''),
                "note_url": row.get('note_url', ''),
            }
        }

    async def _poll_kuaishou(self) -> List[Dict[str, Any]]:
        """Poll new Kuaishou content, filtered by keywords from SlangMapping."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter_title = self._build_keyword_filter('title')
                keyword_filter_desc = self._build_keyword_filter('desc')
                combined_filter = f"({keyword_filter_title} OR {keyword_filter_desc})"

                query = f"""
                    SELECT
                        video_id,
                        user_id,
                        nickname,
                        avatar,
                        title,
                        "desc",
                        liked_count,
                        viewd_count,
                        video_url,
                        video_cover_url,
                        create_time,
                        source_keyword,
                        add_ts,
                        last_modify_ts
                    FROM public.kuaishou_video
                    WHERE add_ts > $1 AND ({combined_filter})
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts = self._last_check_time.get('ks', self.MIN_DATETIME).timestamp()
                rows = await conn.fetch(query, last_ts)

                if rows:
                    self._last_check_time['ks'] = datetime.now()
                    logger.info(f"Polled {len(rows)} new Kuaishou videos (keyword filter: {len(self._keywords)} keywords)")

                return [self._convert_kuaishou_video(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"ks poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_kuaishou_video(row) for row in rows]
            logger.error(f"ks poll failed: {e}")
            return []

    def _convert_kuaishou_video(self, row) -> Dict[str, Any]:
        """Convert Kuaishou video to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"ks_{row.get('video_id')}",
            "source_channel": "kuaishou",
            "group_id": row.get('source_keyword', ''),
            "author_id": str(row.get('user_id', '')),
            "raw_text": f"{row.get('title', '')} {row.get('desc', '')}".strip(),
            "published_at": published_at,
            "metadata": {
                "platform": "kuaishou",
                "content_type": "video",
                "video_id": str(row.get('video_id', '')),
                "title": row.get('title', ''),
                "author": row.get('nickname', ''),
                "liked_count": row.get('liked_count', '0'),
                "view_count": row.get('viewd_count', '0'),
                "video_url": row.get('video_url', ''),
                "ip_location": row.get('ip_location', ''),
                "source_keyword": row.get('source_keyword', ''),
            }
        }

    async def _poll_weibo(self) -> List[Dict[str, Any]]:
        """Poll new Weibo content, filtered by keywords from SlangMapping."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter = self._build_keyword_filter('content')

                query = f"""
                    SELECT
                        note_id,
                        user_id,
                        nickname,
                        avatar,
                        content,
                        liked_count,
                        comments_count,
                        shared_count,
                        create_time,
                        create_date_time,
                        note_url,
                        ip_location,
                        source_keyword,
                        add_ts,
                        last_modify_ts
                    FROM public.weibo_note
                    WHERE add_ts > $1 AND ({keyword_filter})
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts = self._last_check_time.get('weibo', self.MIN_DATETIME).timestamp()
                rows = await conn.fetch(query, last_ts)

                if rows:
                    self._last_check_time['weibo'] = datetime.now()
                    logger.info(f"Polled {len(rows)} new Weibo notes (keyword filter: {len(self._keywords)} keywords)")

                return [self._convert_weibo_note(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"weibo poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_weibo_note(row) for row in rows]
            logger.error(f"weibo poll failed: {e}")
            return []

    def _convert_weibo_note(self, row) -> Dict[str, Any]:
        """Convert Weibo note to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"weibo_{row.get('note_id')}",
            "source_channel": "weibo",
            "group_id": row.get('source_keyword', ''),
            "author_id": str(row.get('user_id', '')),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "weibo",
                "content_type": "note",
                "note_id": str(row.get('note_id', '')),
                "author": row.get('nickname', ''),
                "liked_count": row.get('liked_count', '0'),
                "comment_count": row.get('comments_count', '0'),
                "share_count": row.get('shared_count', '0'),
                "ip_location": row.get('ip_location', ''),
                "source_keyword": row.get('source_keyword', ''),
                "note_url": row.get('note_url', ''),
            }
        }

    async def poll_comments(self, platform: str, content_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Poll comments for specific content.

        Args:
            platform: 'douyin' or 'tieba'
            content_ids: List of content IDs to fetch comments for

        Returns:
            List of RawMessage-formatted comments
        """
        if not self._db_pool:
            await self.initialize()

        if platform == 'douyin':
            return await self._poll_douyin_comments(content_ids)
        elif platform == 'tieba':
            return await self._poll_tieba_comments(content_ids)
        return []

    async def _poll_douyin_comments(self, aweme_ids: List[str]) -> List[Dict[str, Any]]:
        """Poll Douyin comments."""
        if not aweme_ids:
            return []

        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter = self._build_keyword_filter('content')

                query = f"""
                    SELECT
                        comment_id,
                        aweme_id,
                        content,
                        nickname,
                        user_unique_id,
                        create_time,
                        ip_location,
                        like_count,
                        sub_comment_count
                    FROM public.douyin_aweme_comment
                    WHERE aweme_id = ANY($1) AND ({keyword_filter})
                    ORDER BY create_time DESC
                    LIMIT 50
                """
                rows = await conn.fetch(query, aweme_ids)
                logger.info(f"Polled {len(rows)} Douyin comments")
                return [self._convert_douyin_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"douyin_comments poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_douyin_comment(row) for row in rows]
            logger.error(f"douyin_comments poll failed: {e}")
            return []

    def _convert_douyin_comment(self, row) -> Dict[str, Any]:
        """Convert Douyin comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"dy_cmt_{row.get('comment_id')}",
            "source_channel": "douyin",
            "group_id": str(row.get('aweme_id', '')),
            "author_id": str(row.get('user_unique_id', '')),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "douyin",
                "content_type": "comment",
                "aweme_id": str(row.get('aweme_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('nickname', ''),
                "like_count": str(row.get('like_count', '0')),
                "ip_location": row.get('ip_location', ''),
            }
        }

    async def _poll_tieba_comments(self, post_ids: List[str]) -> List[Dict[str, Any]]:
        """Poll Tieba comments."""
        if not post_ids:
            return []

        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                keyword_filter = self._build_keyword_filter('content')

                query = f"""
                    SELECT
                        comment_id,
                        post_id,
                        content,
                        author,
                        create_time,
                        ip_location,
                        agree_num
                    FROM public.tieba_comment
                    WHERE post_id = ANY($1) AND ({keyword_filter})
                    ORDER BY create_time DESC
                    LIMIT 50
                """
                rows = await conn.fetch(query, post_ids)
                logger.info(f"Polled {len(rows)} Tieba comments")
                return [self._convert_tieba_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"tieba_comments poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_tieba_comment(row) for row in rows]
            logger.error(f"tieba_comments poll failed: {e}")
            return []

    def _convert_tieba_comment(self, row) -> Dict[str, Any]:
        """Convert Tieba comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"tieba_cmt_{row.get('comment_id')}",
            "source_channel": "baidu_tieba",
            "group_id": str(row.get('post_id', '')),
            "author_id": str(row.get('author', '')),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "baidu_tieba",
                "content_type": "comment",
                "post_id": str(row.get('post_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('author', ''),
                "agree_num": str(row.get('agree_num', '0')),
                "ip_location": row.get('ip_location', ''),
            }
        }


class MediaCrawlerKafkaProducer:
    """
    Sends MediaCrawler content to Kafka for AntiBlack pipeline processing.
    """

    def __init__(self, kafka_bootstrap_servers: str):
        self.bootstrap_servers = kafka_bootstrap_servers
        self._producer = None
        self._demo_mode = True

    async def start(self) -> None:
        """Initialize Kafka producer."""
        if self._demo_mode:
            logger.info("Kafka producer running in demo mode (MediaCrawler)")
            return

        try:
            from aiokafka import AIOKafkaProducer
            import json
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
            )
            await self._producer.start()
            logger.info(f"Kafka producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.warning(f"Failed to connect to Kafka, using demo mode: {e}")
            self._demo_mode = True

    async def stop(self) -> None:
        """Stop Kafka producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def send_raw_messages(self, messages: List[Dict[str, Any]], topic: str = "raw.messages") -> int:
        """
        Send raw messages to Kafka topic.

        Args:
            messages: List of RawMessage items
            topic: Kafka topic name

        Returns:
            Number of messages sent
        """
        if self._demo_mode:
            logger.info(f"[Demo] Would send {len(messages)} messages to {topic}")
            for msg in messages[:3]:
                logger.info(f"  - {msg.get('message_id')}: {msg.get('raw_text', '')[:50]}...")
            return len(messages)

        sent = 0
        for msg in messages:
            try:
                await self._producer.send_and_wait(topic, msg, key=msg.get('message_id'))
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send message {msg.get('message_id')}: {e}")

        return sent