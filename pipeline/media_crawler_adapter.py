"""
MediaCrawler Adapter for AntiBlack pipeline.
Polls MediaCrawler PostgreSQL database for new content and feeds into AntiBlack pipeline.
Uses SlangMapping (confirmed slang) as keywords for content filtering.
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


# ByteDance-scoped fallback black-market keywords.
# Ensures the crawler can find suspicious content even when 0 slangs are
# CONFIRMED (cold-start scenario). These are the core vocabulary that appears
# in any 字节系 (Douyin/XHS/Tieba) 黑灰产 context.
_FALLBACK_BLACK_MARKET_KEYWORDS: List[str] = [
    "出抖号", "租号", "回收账号", "出号", "加V", "换绑",
    "微信号", "刷粉", "刷赞", "群控", "抖音号买卖",
    "接码", "实名认证", "代实名", "解封", "实名",
    "千粉", "加微",
]


class MediaCrawlerAdapter:
    """
    Adapter that bridges MediaCrawler storage to AntiBlack pipeline.
    Polls MediaCrawler PostgreSQL database for new content.
    Uses SlangMapping (confirmed slang) as采集关键词.
    """
    MIN_DATETIME = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    KEYWORDS_CACHE_TTL = 300  # 5 minutes; avoids per-poll DB hit

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._db_pool: Optional[asyncpg.Pool] = None
        # Cursor is stored as Unix epoch MILLISECONDS (int), matching the
        # `add_ts` / `last_modify_ts` BIGINT columns in MediaCrawler tables.
        # This avoids any timezone/precision ambiguity when comparing to add_ts
        # in SQL. Conversion to/from datetime happens only at the
        # crawler_sync_state boundary (TIMESTAMPTZ column).
        self._last_check_time: Dict[str, int] = {}
        # Separate cursor for comment polls. Tracks `_comment` tables
        # independently so comment-pipeline lag never skips posts or vice versa.
        self._last_check_time_comments: Dict[str, int] = {}
        self._keywords: List[str] = []
        self._keywords_loaded_at: float = 0.0
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

        # Restore per-platform cursors from DB so restarts don't replay history
        await self._restore_cursors()

        logger.info("MediaCrawler adapter initialized")

    async def finalize(self) -> None:
        """Close database connection pool."""
        if self._db_pool:
            await self._db_pool.close()
            self._db_pool = None

    async def _restore_cursors(self) -> None:
        """Load per-platform cursors from PG on startup. Missing platforms default to 0.

        State table column `last_check_time` is TIMESTAMPTZ; we convert to int ms
        (matching add_ts BIGINT) so SQL WHERE add_ts > $1 comparisons work.

        Comment cursor (last_check_time_comments) is nullable: NULL means
        "never backfilled" → fall back to NOW() so the live publisher does
        NOT re-process the 37k historical comments (those are handled by the
        one-time backfill_comments.py script).
        """
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT platform, last_check_time, last_check_time_comments
                       FROM public.crawler_sync_state"""
                )
            for r in rows:
                # Post cursor
                dt = r['last_check_time']
                self._last_check_time[r['platform']] = int(dt.timestamp() * 1000)
                # Comment cursor — NULL → NOW() (skip historical; backfill handles it)
                cdt = r['last_check_time_comments']
                if cdt is None:
                    cdt = datetime.now(timezone.utc)
                    logger.info(
                        f"Comment cursor for {r['platform']} is NULL; "
                        f"bootstrapping to NOW() — historical comments must be "
                        f"backfilled via scripts/backfill_comments.py"
                    )
                self._last_check_time_comments[r['platform']] = int(cdt.timestamp() * 1000)
            logger.info(f"Restored {len(rows)} platform cursors from DB")
        except Exception as e:
            logger.error(f"Failed to restore cursors (continuing with empty state): {e}")

    async def _save_cursor(self, platform: str, ts: datetime, count: int) -> None:
        """UPSERT cursor + counters after a poll. Best-effort: failure does not break the poll."""
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.crawler_sync_state
                        (platform, last_check_time, last_poll_count, total_polled, last_status, updated_at)
                    VALUES ($1, $2, $3::int, $3::bigint, 'ok', NOW())
                    ON CONFLICT (platform) DO UPDATE SET
                        last_check_time = EXCLUDED.last_check_time,
                        last_poll_count = EXCLUDED.last_poll_count,
                        total_polled = public.crawler_sync_state.total_polled + EXCLUDED.total_polled,
                        last_status = 'ok',
                        updated_at = NOW()
                    """,
                    platform, ts, count,
                )
        except Exception as e:
            logger.warning(f"Failed to save cursor for {platform}: {e}")

    async def _save_comments_cursor(self, platform: str, ts: datetime, count: int) -> None:
        """UPSERT comment cursor + counters. Same UPSERT pattern as _save_cursor
        but writes to the *_comments columns added in migration 2026-06-03.

        Note: the INSERT clause must provide ALL 9 columns. The original
        bug (2026-06-03) only listed 6 and the missing `last_check_time`
        (NOT NULL, no DEFAULT) caused the UPSERT to fail with
        "null value in column 'last_check_time' violates not-null
        constraint" when the INSERT path was taken (e.g., for a new
        platform row that didn't exist yet). The fix: also write
        `last_check_time = NOW()` and zeroed counters in the INSERT
        clause so the new row satisfies all NOT NULL constraints.
        """
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.crawler_sync_state
                        (platform,
                         last_check_time, last_check_time_comments,
                         last_poll_count, last_poll_count_comments,
                         total_polled, total_polled_comments,
                         last_status, updated_at)
                    VALUES ($1,
                            NOW(), $2,
                            0,      $3::int,
                            0,      $3::bigint,
                            'ok',   NOW())
                    ON CONFLICT (platform) DO UPDATE SET
                        last_check_time_comments = EXCLUDED.last_check_time_comments,
                        last_poll_count_comments = EXCLUDED.last_poll_count_comments,
                        total_polled_comments =
                            COALESCE(public.crawler_sync_state.total_polled_comments, 0)
                            + EXCLUDED.total_polled_comments,
                        last_status = 'ok',
                        updated_at = NOW()
                    """,
                    platform, ts, count,
                )
        except Exception as e:
            logger.warning(f"Failed to save comments cursor for {platform}: {e}")

    async def sync_keywords_from_slang_mapping(self) -> List[str]:
        """
        Sync keywords from SlangMapping (confirmed slang).
        黑话 = 关键词，从PostgreSQL读取已确认的黑话作为采集关键词。

        5-minute TTL cache avoids hitting DB on every poll. Always merges with
        _FALLBACK_BLACK_MARKET_KEYWORDS so the crawler can find suspicious
        content even with 0 CONFIRMED slangs (cold-start protection).
        """
        # TTL cache hit — no DB call
        if self._keywords and (time.time() - self._keywords_loaded_at) < self.KEYWORDS_CACHE_TTL:
            return self._keywords

        if not self._pg_db:
            self._pg_db = PostgreSQLService.get_instance()

        try:
            # Read all verified (CONFIRMED) slang mappings
            slang_mappings = self._pg_db.get_all_slang_mappings(verified_only=True)
            keywords = [m['slang_raw'] for m in slang_mappings if m.get('slang_raw')]

            if keywords:
                logger.info(f"Synced {len(keywords)} keywords from SlangMapping: {keywords[:5]}...")
            else:
                logger.warning(f"SlangMapping empty; relying on FALLBACK keywords only")

            # Always merge with FALLBACK keywords (union, dedup) — cold-start safety net
            merged = list(dict.fromkeys(keywords + _FALLBACK_BLACK_MARKET_KEYWORDS))
            old_keywords = self._keywords
            self._keywords = merged
            self._keywords_loaded_at = time.time()
            if set(old_keywords) != set(merged):
                logger.info(
                    f"Keywords updated: total={len(merged)} "
                    f"(CONFIRMED={len(keywords)}, FALLBACK={len(_FALLBACK_BLACK_MARKET_KEYWORDS)})"
                )
            return self._keywords
        except Exception as e:
            logger.error(f"Failed to sync keywords from SlangMapping: {e}")
            # Last-resort fallback: use FALLBACK list verbatim (no DB required)
            self._keywords = list(_FALLBACK_BLACK_MARKET_KEYWORDS)
            self._keywords_loaded_at = time.time()
            return self._keywords

    async def poll_new_content(self, platform: str) -> List[Dict[str, Any]]:
        """
        Poll new content from MediaCrawler database.

        Per design (2026-06-03): NO keyword filter at this layer. The pipeline
        (Cleaner → Classifier → Extractor → Router) is the only layer that
        decides what is a clue and what escalates to the LLM. Filtering here
        would silently drop content that the pipeline could have classified.

        MediaCrawler itself still searches by SlangMapping keywords (handled
        in multi_crawler_scheduler.py), which determines the crawl scope.

        Args:
            platform: 'douyin' | 'tieba' | 'xhs' | 'ks' | 'weibo'

        Returns:
            List of RawMessage-formatted content items
        """
        if not self._db_pool:
            await self.initialize()

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

    async def _poll_douyin(self) -> List[Dict[str, Any]]:
        """Poll new Douyin content. No keyword filter — pipeline decides."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
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
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts_ms = self._last_check_time.get('douyin', 0)
                rows = await conn.fetch(query, last_ts_ms)

                if rows:
                    # add_ts is BIGINT (Unix ms). Use MAX(add_ts) as cursor,
                    # NOT datetime.now() — avoids permanently skipping rows
                    # that arrive between fetch and cursor commit.
                    max_cursor_ms = max(r['add_ts'] for r in rows)
                    self._last_check_time['douyin'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_cursor('douyin', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Douyin videos")

                return [self._convert_douyin_video(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"douyin poll succeeded but cleanup failed, returning {len(rows)} rows")
                return [self._convert_douyin_video(row) for row in rows]
            logger.error(f"douyin poll failed: {e}")
            return []

    async def _poll_tieba(self) -> List[Dict[str, Any]]:
        """Poll new Tieba content. No keyword filter — pipeline decides."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                # last_modify_ts is millisecond timestamp (BIGINT), add_ts is NULL for all records.
                # Both columns are BIGINT (Unix ms), so cursor is also int ms.
                last_ts_ms = self._last_check_time.get('tieba', 0)

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
                    ORDER BY COALESCE(add_ts, last_modify_ts) ASC
                    LIMIT 100
                """

                # $1 and $2 are both int ms to match the BIGINT columns
                rows = await conn.fetch(query, last_ts_ms, last_ts_ms)

                if rows:
                    # Tieba add_ts is mostly NULL; fall back to last_modify_ts (ms) for cursor.
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time['tieba'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_cursor('tieba', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Tieba posts")

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
            if create_time > 100000000000:
                create_time = create_time / 1000
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
            if publish_time > 100000000000:
                publish_time = publish_time / 1000
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
        """Poll new Xiaohongshu content. No keyword filter — pipeline decides."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
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
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts_ms = self._last_check_time.get('xhs', 0)
                rows = await conn.fetch(query, last_ts_ms)

                if rows:
                    max_cursor_ms = max(r['add_ts'] for r in rows)
                    self._last_check_time['xhs'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_cursor('xhs', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Xiaohongshu notes")

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
            if time_val > 100000000000:
                time_val = time_val / 1000
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
        """Poll new Kuaishou content. No keyword filter — pipeline decides."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
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
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts_ms = self._last_check_time.get('ks', 0)
                rows = await conn.fetch(query, last_ts_ms)

                if rows:
                    max_cursor_ms = max(r['add_ts'] for r in rows)
                    self._last_check_time['ks'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_cursor('ks', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Kuaishou videos")

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
            if create_time > 100000000000:
                create_time = create_time / 1000
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
        """Poll new Weibo content. No keyword filter — pipeline decides."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
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
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 100
                """

                last_ts_ms = self._last_check_time.get('weibo', 0)
                rows = await conn.fetch(query, last_ts_ms)

                if rows:
                    max_cursor_ms = max(r['add_ts'] for r in rows)
                    self._last_check_time['weibo'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_cursor('weibo', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Weibo notes")

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
            if create_time > 100000000000:
                create_time = create_time / 1000
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

    # =====================================================================
    # Comment polling (added 2026-06-03)
    # Cursor-based, no keyword filter — same architecture as post polls.
    # Old API `poll_comments(platform, content_ids)` (the per-content-id
    # request-response shape) is gone; comments now flow as a stream.
    # =====================================================================

    async def poll_new_comments(self, platform: str) -> List[Dict[str, Any]]:
        """
        Poll new comments from MediaCrawler database for the given platform.

        No keyword filter — pipeline decides. Each call advances the
        per-platform comment cursor in crawler_sync_state.last_check_time_comments.
        On first startup (column NULL), the cursor bootstraps to NOW() so the
        live publisher does NOT re-process historical comments (those are
        handled by scripts/backfill_comments.py).
        """
        if not self._db_pool:
            await self.initialize()

        if platform == 'douyin':
            return await self._poll_douyin_comments_cursor()
        elif platform == 'tieba':
            return await self._poll_tieba_comments_cursor()
        elif platform == 'xhs':
            return await self._poll_xhs_comments_cursor()
        elif platform == 'ks':
            return await self._poll_kuaishou_comments_cursor()
        elif platform == 'weibo':
            return await self._poll_weibo_comments_cursor()
        else:
            logger.warning(f"Unsupported platform for comments: {platform}")
            return []

    async def _poll_douyin_comments_cursor(self) -> List[Dict[str, Any]]:
        """Poll new Douyin comments since the last cursor."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                last_ts_ms = self._last_check_time_comments.get('douyin', 0)
                query = """
                    SELECT
                        comment_id,
                        aweme_id,
                        content,
                        nickname,
                        user_unique_id,
                        create_time,
                        ip_location,
                        like_count,
                        sub_comment_count,
                        add_ts,
                        last_modify_ts
                    FROM public.douyin_aweme_comment
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 200
                """
                rows = await conn.fetch(query, last_ts_ms)
                if rows:
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time_comments['douyin'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_comments_cursor('douyin', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Douyin comments")
                return [self._convert_douyin_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"douyin comments poll: cursor advanced, returning {len(rows)} rows")
                return [self._convert_douyin_comment(row) for row in rows]
            logger.error(f"douyin comments poll failed: {e}")
            return []

    async def _poll_tieba_comments_cursor(self) -> List[Dict[str, Any]]:
        """Poll new Tieba comments. add_ts is NULL for all rows; use last_modify_ts."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                last_ts_ms = self._last_check_time_comments.get('tieba', 0)
                query = """
                    SELECT
                        comment_id,
                        note_id,
                        content,
                        user_nickname,
                        publish_time,
                        ip_location,
                        sub_comment_count,
                        add_ts,
                        last_modify_ts
                    FROM public.tieba_comment
                    WHERE (add_ts IS NOT NULL AND add_ts > $1)
                       OR (add_ts IS NULL AND last_modify_ts > $2)
                    ORDER BY COALESCE(add_ts, last_modify_ts) ASC
                    LIMIT 200
                """
                rows = await conn.fetch(query, last_ts_ms, last_ts_ms)
                if rows:
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time_comments['tieba'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_comments_cursor('tieba', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Tieba comments")
                return [self._convert_tieba_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"tieba comments poll: cursor advanced, returning {len(rows)} rows")
                return [self._convert_tieba_comment(row) for row in rows]
            logger.error(f"tieba comments poll failed: {e}")
            return []

    async def _poll_xhs_comments_cursor(self) -> List[Dict[str, Any]]:
        """Poll new Xiaohongshu comments."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                last_ts_ms = self._last_check_time_comments.get('xhs', 0)
                query = """
                    SELECT
                        comment_id,
                        note_id,
                        content,
                        nickname,
                        user_id,
                        create_time,
                        ip_location,
                        like_count,
                        add_ts,
                        last_modify_ts
                    FROM public.xhs_note_comment
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 200
                """
                rows = await conn.fetch(query, last_ts_ms)
                if rows:
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time_comments['xhs'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_comments_cursor('xhs', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new XHS comments")
                return [self._convert_xhs_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"xhs comments poll: cursor advanced, returning {len(rows)} rows")
                return [self._convert_xhs_comment(row) for row in rows]
            logger.error(f"xhs comments poll failed: {e}")
            return []

    async def _poll_weibo_comments_cursor(self) -> List[Dict[str, Any]]:
        """Poll new Weibo comments."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                last_ts_ms = self._last_check_time_comments.get('weibo', 0)
                query = """
                    SELECT
                        comment_id,
                        note_id,
                        content,
                        nickname,
                        user_id,
                        create_time,
                        ip_location,
                        comment_like_count,
                        add_ts,
                        last_modify_ts
                    FROM public.weibo_note_comment
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 200
                """
                rows = await conn.fetch(query, last_ts_ms)
                if rows:
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time_comments['weibo'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_comments_cursor('weibo', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Weibo comments")
                return [self._convert_weibo_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"weibo comments poll: cursor advanced, returning {len(rows)} rows")
                return [self._convert_weibo_comment(row) for row in rows]
            logger.error(f"weibo comments poll failed: {e}")
            return []

    async def _poll_kuaishou_comments_cursor(self) -> List[Dict[str, Any]]:
        """Poll new Kuaishou comments. kuaishou_video_comment is currently empty
        in production, but the poll is wired in so the live publisher will pick
        up comments as soon as MediaCrawler starts writing them."""
        rows = []
        try:
            async with self._db_pool.acquire() as conn:
                last_ts_ms = self._last_check_time_comments.get('ks', 0)
                query = """
                    SELECT
                        comment_id,
                        video_id,
                        content,
                        nickname,
                        user_id,
                        create_time,
                        add_ts,
                        last_modify_ts
                    FROM public.kuaishou_video_comment
                    WHERE add_ts > $1
                    ORDER BY add_ts ASC
                    LIMIT 200
                """
                rows = await conn.fetch(query, last_ts_ms)
                if rows:
                    max_cursor_ms = max(
                        r['add_ts'] if r['add_ts'] is not None else r['last_modify_ts']
                        for r in rows
                    )
                    self._last_check_time_comments['ks'] = max_cursor_ms
                    cursor_dt = datetime.fromtimestamp(max_cursor_ms / 1000, tz=timezone.utc)
                    await self._save_comments_cursor('ks', cursor_dt, len(rows))
                    logger.info(f"Polled {len(rows)} new Kuaishou comments")
                return [self._convert_kuaishou_comment(row) for row in rows]
        except Exception as e:
            if rows:
                logger.warning(f"kuaishou comments poll: cursor advanced, returning {len(rows)} rows")
                return [self._convert_kuaishou_comment(row) for row in rows]
            logger.error(f"kuaishou comments poll failed: {e}")
            return []

    def _convert_douyin_comment(self, row) -> Dict[str, Any]:
        """Convert Douyin comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            if create_time > 100000000000:
                create_time = create_time / 1000
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"dy_cmt_{row.get('comment_id')}",
            "source_channel": "douyin",
            "group_id": str(row.get('aweme_id', '')),
            "author_id": str(row.get('user_unique_id', '') or ''),
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

    def _convert_tieba_comment(self, row) -> Dict[str, Any]:
        """Convert Tieba comment to RawMessage format."""
        # tieba_comment has `publish_time` (ms epoch), not `create_time`.
        # The old converter used `create_time` which is not in this table.
        publish_time = row.get('publish_time', 0)
        if isinstance(publish_time, int):
            if publish_time > 100000000000:
                publish_time = publish_time / 1000
            published_at = datetime.fromtimestamp(publish_time).isoformat()
        else:
            published_at = str(publish_time)

        return {
            "message_id": f"tieba_cmt_{row.get('comment_id')}",
            "source_channel": "baidu_tieba",
            "group_id": str(row.get('note_id', '')),
            "author_id": str(row.get('user_nickname', '')),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "baidu_tieba",
                "content_type": "comment",
                "note_id": str(row.get('note_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('user_nickname', ''),
                "sub_comment_count": str(row.get('sub_comment_count', '0')),
                "ip_location": row.get('ip_location', ''),
            }
        }

    def _convert_xhs_comment(self, row) -> Dict[str, Any]:
        """Convert Xiaohongshu comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            if create_time > 100000000000:
                create_time = create_time / 1000
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"xhs_cmt_{row.get('comment_id')}",
            "source_channel": "xiaohongshu",
            "group_id": str(row.get('note_id', '')),
            "author_id": str(row.get('user_id', '') or ''),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "xiaohongshu",
                "content_type": "comment",
                "note_id": str(row.get('note_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('nickname', ''),
                "like_count": str(row.get('like_count', '0')),
                "ip_location": row.get('ip_location', ''),
            }
        }

    def _convert_weibo_comment(self, row) -> Dict[str, Any]:
        """Convert Weibo comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            if create_time > 100000000000:
                create_time = create_time / 1000
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"weibo_cmt_{row.get('comment_id')}",
            "source_channel": "weibo",
            "group_id": str(row.get('note_id', '')),
            "author_id": str(row.get('user_id', '') or ''),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "weibo",
                "content_type": "comment",
                "note_id": str(row.get('note_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('nickname', ''),
                "like_count": str(row.get('comment_like_count', '0')),
                "ip_location": row.get('ip_location', ''),
            }
        }

    def _convert_kuaishou_comment(self, row) -> Dict[str, Any]:
        """Convert Kuaishou comment to RawMessage format."""
        create_time = row.get('create_time', 0)
        if isinstance(create_time, int):
            if create_time > 100000000000:
                create_time = create_time / 1000
            published_at = datetime.fromtimestamp(create_time).isoformat()
        else:
            published_at = str(create_time)

        return {
            "message_id": f"ks_cmt_{row.get('comment_id')}",
            "source_channel": "kuaishou",
            "group_id": str(row.get('video_id', '')),
            "author_id": str(row.get('user_id', '') or ''),
            "raw_text": row.get('content', ''),
            "published_at": published_at,
            "metadata": {
                "platform": "kuaishou",
                "content_type": "comment",
                "video_id": str(row.get('video_id', '')),
                "comment_id": str(row.get('comment_id', '')),
                "author": row.get('nickname', ''),
                "ip_location": "",
            }
        }


class MediaCrawlerKafkaProducer:
    """
    Sends MediaCrawler content to Kafka for AntiBlack pipeline processing.
    """

    def __init__(self, kafka_bootstrap_servers: str):
        self.bootstrap_servers = kafka_bootstrap_servers
        self._producer = None

    async def start(self) -> None:
        """Initialize Kafka producer."""

        try:
            from aiokafka import AIOKafkaProducer
            import json
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if isinstance(k, str) else k,
            )
            await self._producer.start()
            logger.info(f"Kafka producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise e

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
        if not self._producer:
            logger.error("MediaCrawler Kafka producer not initialized")
            return 0

        sent = 0
        for msg in messages:
            try:
                await self._producer.send_and_wait(topic, msg, key=msg.get('message_id'))
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send message {msg.get('message_id')}: {e}")

        return sent