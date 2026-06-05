"""
One-time backfill for the 37k historical comments sitting in
media_crawler.public.*_comment tables (never read by the original
MediaCrawlerAdapter which only polled post tables).

Design notes:
  - Drains to Kafka `raw.messages` topic; same format as live poll,
    so the daemon's existing `_process_messages` handles them unchanged.
  - DOES NOT update crawler_sync_state.last_check_time_comments. After
    backfill finishes, that column is still NULL; the live publisher's
    `_restore_cursors` reads NULL → bootstraps to NOW() → only sees new
    comments, no duplicates with what backfill pushed.
  - Batches of 500 with 0.5s sleep between batches: protects DB from
    a tight read loop and gives the Kafka producer time to flush its
    internal queue.
  - 4 platforms: douyin, tieba, xhs, weibo. kuaishou_video_comment
    is currently empty in production; included anyway so the script
    will pick up comments the moment MediaCrawler starts writing them.
"""
import asyncio
import io
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from config import get_config
from pipeline.media_crawler_adapter import MediaCrawlerAdapter, MediaCrawlerKafkaProducer
from utils.logger import configure_root_logger

configure_root_logger()
logger = logging.getLogger("backfill_comments")


PLATFORMS = ["douyin", "tieba", "xhs", "weibo", "ks"]
BATCH_SIZE = 500
INTER_BATCH_SLEEP = 0.5  # seconds


async def backfill_platform(adapter, producer, platform: str, batch_size: int):
    """Drain all comments for `platform` from epoch → now into Kafka.

    Bypasses the adapter's per-platform cursor machinery entirely:
    opens a fresh DB pool / cursor and runs the SELECT directly with
    cursor starting at 0 (Unix epoch ms). Adapter is only used for
    row→message conversion (so message format matches live poll output
    exactly).
    """
    if not adapter._db_pool:
        await adapter.initialize()

    converter = _get_converter(platform)
    if converter is None:
        logger.warning(f"[{platform}] no converter implemented, skipping")
        return 0

    if platform == "tieba":
        # tieba_comment has add_ts = NULL for all rows; use last_modify_ts
        sql_query = f"""
            SELECT *, add_ts, last_modify_ts
            FROM public.tieba_comment
            WHERE (add_ts IS NOT NULL AND add_ts > $1)
               OR (add_ts IS NULL AND last_modify_ts > $2)
            ORDER BY COALESCE(add_ts, last_modify_ts) ASC
            LIMIT {batch_size}
        """
    else:
        table = _comment_table(platform)
        sql_query = f"""
            SELECT * FROM public.{table}
            WHERE add_ts > $1
            ORDER BY add_ts ASC
            LIMIT {batch_size}
        """

    cursor_ms = 0
    total = 0
    start = time.time()

    async with adapter._db_pool.acquire() as conn:
        while True:
            if platform == "tieba":
                rows = await conn.fetch(sql_query, cursor_ms, cursor_ms)
            else:
                rows = await conn.fetch(sql_query, cursor_ms)
            if not rows:
                break

            messages = [converter(row) for row in rows]
            sent = await producer.send_raw_messages(messages)
            total += sent

            # Advance cursor to MAX timestamp of this batch
            new_cursor_ms = max(
                r["add_ts"] if r["add_ts"] is not None else r["last_modify_ts"]
                for r in rows
            )
            if new_cursor_ms == cursor_ms:
                # Defensive: avoid infinite loop if all rows have same ts
                # (very unlikely with add_ts/last_modify_ts being ms-precision,
                # but break just in case)
                logger.warning(
                    f"[{platform}] cursor stuck at {cursor_ms} after {total} rows; "
                    f"advancing by 1ms to break"
                )
                cursor_ms += 1
            else:
                cursor_ms = new_cursor_ms

            logger.info(
                f"[{platform}] backfilled batch={len(rows)} total={total} "
                f"cursor={datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc).isoformat()}"
            )
            await asyncio.sleep(INTER_BATCH_SLEEP)

    elapsed = time.time() - start
    rate = total / elapsed if elapsed > 0 else 0
    logger.info(
        f"[{platform}] DONE  total={total}  elapsed={elapsed:.1f}s  rate={rate:.1f}/s"
    )
    return total


def _comment_table(platform: str) -> str:
    return {
        "douyin":   "douyin_aweme_comment",
        "xhs":      "xhs_note_comment",
        "weibo":    "weibo_note_comment",
        "ks":       "kuaishou_video_comment",
    }[platform]


def _get_converter(platform: str):
    """Return the adapter's row→RawMessage converter for the given platform's comments."""
    # We instantiate a throwaway adapter just to call the converters.
    # The converters are pure functions of the row dict and have no
    # instance state.
    tmp = MediaCrawlerAdapter({})
    return {
        "douyin": tmp._convert_douyin_comment,
        "tieba":  tmp._convert_tieba_comment,
        "xhs":    tmp._convert_xhs_comment,
        "weibo":  tmp._convert_weibo_comment,
        "ks":     tmp._convert_kuaishou_comment,
    }.get(platform)


async def main():
    config = get_config()
    adapter = MediaCrawlerAdapter(config)
    # initialize() will read cursors from DB but we don't care about
    # the post cursor here — backfill only uses the DB pool and converters.
    await adapter.initialize()

    kafka_servers = config.get("kafka", {}).get("bootstrap_servers", "localhost:9092")
    topic = config.get("kafka", {}).get("topics", {}).get("raw_messages", "raw.messages")
    producer = MediaCrawlerKafkaProducer(kafka_servers)
    producer._topic = topic  # ensure producer uses correct topic
    await producer.start()

    overall_start = time.time()
    summary = []
    try:
        for p in PLATFORMS:
            n = await backfill_platform(adapter, producer, p, BATCH_SIZE)
            summary.append((p, n))
    finally:
        await producer.stop()
        await adapter.finalize()

    elapsed = time.time() - overall_start
    grand_total = sum(n for _, n in summary)
    print("\n========== BACKFILL SUMMARY ==========")
    for p, n in summary:
        print(f"  {p:<8} {n:>7d} comments")
    print(f"  {'TOTAL':<8} {grand_total:>7d} comments in {elapsed:.1f}s")
    print("======================================\n")
    print("Daemon's `_process_messages` will pick these up from Kafka")
    print("and process them through Cleaner → Classifier → Extractor → Router.")
    print("Watch `antiblack.clues WHERE message_id LIKE '%_cmt_%'` for new rows.")


if __name__ == "__main__":
    asyncio.run(main())
