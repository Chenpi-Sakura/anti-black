"""
Independent Publisher Process for MediaCrawler.
Polls data from the MediaCrawler database and publishes it to the Kafka `raw.messages` topic.
"""
import asyncio
import logging
import signal
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from pipeline.media_crawler_adapter import MediaCrawlerAdapter, MediaCrawlerKafkaProducer

from utils.logger import configure_root_logger
configure_root_logger()
logger = logging.getLogger(__name__)


class MediaCrawlerPublisher:
    def __init__(self, config):
        self.config = config
        self._running = False
        self._adapter = MediaCrawlerAdapter(self.config)
        kafka_servers = self.config.get('kafka', {}).get('bootstrap_servers', 'localhost:9092')
        self._producer = MediaCrawlerKafkaProducer(kafka_servers)
        self._topic = self.config.get('kafka', {}).get('topics', {}).get('raw_messages', 'raw.messages')
        
    async def start(self):
        logger.info("Starting MediaCrawler Publisher Process")
        await self._adapter.initialize()
        await self._producer.start()
        self._running = True

        # Safety net: ensure every enabled platform has a cursor row in DB.
        # Without this, a new platform added to config.yaml would replay all
        # history on the first poll. Idempotent: existing rows are untouched.
        await self._ensure_cursor_rows()

        interval = self.config.get('media_crawler', {}).get('poll_interval', 900)
        platforms = [p['name'] for p in self.config.get('media_crawler', {}).get('platforms', []) if p.get('enabled', False)]

        if not platforms:
            logger.warning("No platforms enabled in configuration.")
            
        while self._running:
            for platform in platforms:
                try:
                    logger.info(f"Polling content for platform: {platform}")
                    messages = await self._adapter.poll_new_content(platform)
                    if messages:
                        sent = await self._producer.send_raw_messages(messages, topic=self._topic)
                        logger.info(f"Published {sent}/{len(messages)} messages from {platform} to {self._topic}")
                    else:
                        logger.info(f"No new content found for {platform}")
                except Exception as e:
                    logger.error(f"Error polling/publishing for {platform}: {e}", exc_info=True)
            
            logger.info(f"Waiting {interval} seconds before next poll...")
            await asyncio.sleep(interval)
            
    async def stop(self):
        logger.info("Stopping MediaCrawler Publisher Process")
        self._running = False
        await self._producer.stop()
        await self._adapter.finalize()

    async def _ensure_cursor_rows(self) -> None:
        """Ensure every enabled platform has a cursor row in crawler_sync_state. Bootstrap to NOW() if missing."""
        platforms = [p['name'] for p in self.config.get('media_crawler', {}).get('platforms', []) if p.get('enabled', False)]
        if not platforms or not self._adapter._db_pool:
            return
        try:
            async with self._adapter._db_pool.acquire() as conn:
                for p in platforms:
                    await conn.execute(
                        """
                        INSERT INTO media_crawler.public.crawler_sync_state
                            (platform, last_check_time)
                        VALUES ($1, NOW())
                        ON CONFLICT (platform) DO NOTHING
                        """,
                        p,
                    )
            logger.info(f"Ensured {len(platforms)} cursor rows in DB")
        except Exception as e:
            logger.error(f"Failed to ensure cursor rows: {e}")


async def main():
    config = get_config()
    publisher = MediaCrawlerPublisher(config)
    
    loop = asyncio.get_event_loop()
    if os.name != 'nt':
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(publisher.stop()))
        
    try:
        await publisher.start()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        if publisher._running:
            await publisher.stop()

if __name__ == '__main__':
    asyncio.run(main())
