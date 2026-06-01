import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from utils.logger import configure_root_logger
configure_root_logger()
logger = logging.getLogger(__name__)

import json
import time
import asyncio
import signal
import argparse
from datetime import datetime
from typing import Optional

import httpx

# Platform configs
PLATFORM_CONFIGS = {
    "dy": {
        "config_file": "start_dy.json",
        "keywords": ["抖音号买卖", "租号", "刷粉", "刷赞", "出抖号", "收号", "加V", "换绑", "微信号", "群控"],
        "platform": "dy",
        "login_type": "cookie",
        "crawler_type": "search",
        "save_option": "postgres",
    },
    "tieba": {
        "config_file": "start_tieba.json",
        "keywords": ["抖音号买卖", "租号", "刷粉", "刷赞", "出抖号", "收号", "加V", "换绑", "微信号", "群控"],
        "platform": "tieba",
        "login_type": "cookie",
        "crawler_type": "search",
        "save_option": "postgres",
    },
    "ks": {
        "config_file": "start_ks.json",
        "keywords": ["抖音号买卖", "租号", "刷粉", "刷赞", "出抖号", "收号", "加V", "换绑", "微信号", "群控"],
        "platform": "ks",
        "login_type": "cookie",
        "crawler_type": "search",
        "save_option": "postgres",
    },
    "wb": {
        "config_file": "start_weibo.json",
        "keywords": ["抖音号买卖", "租号", "刷粉", "刷赞", "出抖号", "收号", "加V", "换绑", "微信号", "群控"],
        "platform": "wb",
        "login_type": "cookie",
        "crawler_type": "search",
        "save_option": "postgres",
    },
    "xhs": {
        "config_file": "start_xhs.json",
        "keywords": ["抖音号买卖", "租号", "刷粉", "刷赞", "出抖号", "收号", "加V", "换绑", "微信号", "群控"],
        "platform": "xhs",
        "login_type": "cookie",
        "crawler_type": "search",
        "save_option": "postgres",
    },
}

API_BASE = "http://127.0.0.1:8092"


class MultiCrawlerScheduler:
    def __init__(self, api_base: str = API_BASE):
        self.api_base = api_base
        self.running = False
        self.current_platform: Optional[str] = None

    async def wait_for_completion(self, timeout: int = 3600) -> bool:
        """Wait for crawler to complete"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{self.api_base}/api/crawler/status", timeout=5.0)
                    if response.status_code == 200:
                        status = response.json()
                        if status.get("status") == "idle":
                            return True
                        elif status.get("status") == "error":
                            logger.info(f"  [ERROR] Crawler error: {status.get('error_message', 'unknown')}")
                            return False
            except Exception as e:
                logger.info(f"  [WARN] Status check failed: {e}")
            await asyncio.sleep(10)
        logger.info(f"  [TIMEOUT] Crawler did not complete within {timeout}s")
        return False

    async def start_crawler(self, config: dict) -> bool:
        """Start a crawler with given config"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/api/crawler/start",
                    json=config,
                    timeout=10.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "ok":
                        logger.info(f"  [OK] Crawler started for {config['platform']}")
                        return True
                logger.info(f"  [FAIL] Start failed: {response.text}")
                return False
        except Exception as e:
            logger.info(f"  [FAIL] Start exception: {e}")
            return False

    async def stop_crawler(self) -> bool:
        """Stop current crawler"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.api_base}/api/crawler/stop", timeout=10.0)
                return response.status_code == 200
        except:
            return False

    async def run_platform_sequence(self, platforms: list, loop_interval: int = 900):
        """
        Run platforms in sequence, then loop after interval.

        Args:
            platforms: List of platform names to crawl
            loop_interval: Seconds to wait before next cycle (default 15 min)
        """
        cycle = 0
        while self.running:
            cycle += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Cycle #{cycle} started")
            logger.info(f"{'='*60}")

            for platform in platforms:
                if not self.running:
                    break

                self.current_platform = platform
                cfg = PLATFORM_CONFIGS.get(platform)
                if not cfg:
                    logger.info(f"[WARN] Unknown platform: {platform}")
                    continue

                config_file = cfg.get("config_file")
                config_path = Path(config_file)

                # Fetch dynamic keywords from database (Slang Evolution)
                try:
                    from services.database import PostgreSQLService
                    db = PostgreSQLService.get_instance()
                    slang_mappings = db.get_all_slang_mappings(verified_only=True)
                    db_keywords = [m['slang_raw'] for m in slang_mappings if m.get('slang_raw')]
                    
                    if db_keywords:
                        logger.info(f"  [DB SYNC] Fetched {len(db_keywords)} confirmed keywords from Slang Evolution database.")
                        cfg_keywords = db_keywords
                    else:
                        cfg_keywords = cfg["keywords"]
                except Exception as e:
                    logger.warning(f"  [WARN] Failed to fetch keywords from DB: {e}. Using default.")
                    cfg_keywords = cfg["keywords"]

                # Load config from file if exists, otherwise use defaults
                if config_path.exists():
                    with open(config_path, encoding='utf-8') as f:
                        crawler_config = json.load(f)
                        # Override with dynamic keywords
                        crawler_config["keywords"] = ",".join(cfg_keywords)
                else:
                    # Build from defaults
                    crawler_config = {
                        "platform": cfg["platform"],
                        "login_type": cfg["login_type"],
                        "crawler_type": cfg["crawler_type"],
                        "save_option": cfg["save_option"],
                        "keywords": ",".join(cfg_keywords),
                        "headless": False,
                    }

                logger.info(f"\n[{platform.upper()}] Starting crawler...")
                logger.info(f"  Keywords: {crawler_config.get('keywords', 'N/A')}")
                logger.info(f"  Save option: {crawler_config.get('save_option', 'N/A')}")

                # Start crawler
                success = await self.start_crawler(crawler_config)
                if not success:
                    logger.info(f"  [ERROR] Failed to start {platform}, skipping...")
                    continue

                # Wait for completion (max 1 hour per platform)
                completed = await self.wait_for_completion(timeout=3600)
                if not completed:
                    logger.info(f"  [WARN] {platform} did not complete, stopping...")
                    await self.stop_crawler()
                    await asyncio.sleep(5)

                logger.info(f"  [{platform.upper()}] Done")

            if self.running:
                logger.info(f"\n[DONE] Cycle #{cycle} complete. Sleeping {loop_interval}s before next cycle...")
                await asyncio.sleep(loop_interval)

    async def run_single_keyword_batch(self, platform: str, keywords: list):
        """
        Run a single platform with a batch of keywords (one-time run).
        Modifies config to use all keywords at once.
        """
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            logger.info(f"[ERROR] Unknown platform: {platform}")
            return

        config = {
            "platform": cfg["platform"],
            "login_type": cfg["login_type"],
            "crawler_type": cfg["crawler_type"],
            "save_option": cfg.get("save_option", "postgres"),
            "keywords": ",".join(keywords),
            "headless": False,
        }

        logger.info(f"\n[{platform.upper()}] Starting with {len(keywords)} keywords...")
        logger.info(f"  Keywords: {config['keywords']}")

        success = await self.start_crawler(config)
        if not success:
            logger.info(f"  [ERROR] Failed to start crawler")
            return

        await self.wait_for_completion(timeout=7200)  # 2 hour max
        logger.info(f"\n[{platform.upper()}] Completed!")

    def stop(self):
        """Stop the scheduler"""
        logger.info("\n[STOP] Shutting down scheduler...")
        self.running = False


async def main():
    parser = argparse.ArgumentParser(description="Multi-platform crawler scheduler")
    parser.add_argument("--platforms", "-p", default="dy,tieba,ks,wb,xhs",
                        help="Comma-separated platforms to crawl (default: dy,tieba,ks,wb,xhs)")
    parser.add_argument("--interval", "-i", type=int, default=900,
                        help="Loop interval in seconds (default: 900 = 15 min)")
    parser.add_argument("--keywords", "-k", default="",
                        help="Override keywords for all platforms (comma-separated)")
    parser.add_argument("--daemon", "-d", action="store_true",
                        help="Run in daemon mode (loop continuously)")
    parser.add_argument("--single", "-s", action="store_true",
                        help="Single run (no loop)")

    args = parser.parse_args()

    scheduler = MultiCrawlerScheduler()

    # Handle signals
    def signal_handler(sig, frame):
        scheduler.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    platforms = [p.strip() for p in args.platforms.split(",")]

    if args.keywords:
        # Override keywords for all platforms
        for p in PLATFORM_CONFIGS:
            PLATFORM_CONFIGS[p]["keywords"] = [k.strip() for k in args.keywords.split(",")]

    scheduler.running = True

    if args.single:
        # Single run (no loop)
        await scheduler.run_platform_sequence(platforms, loop_interval=999999999)
    elif args.daemon:
        # Daemon mode - loop forever
        logger.info(f"[DAEMON] Starting in daemon mode...")
        logger.info(f"  Platforms: {platforms}")
        logger.info(f"  Interval: {args.interval}s")
        await scheduler.run_platform_sequence(platforms, loop_interval=args.interval)
    else:
        # Default: run sequence once
        await scheduler.run_platform_sequence(platforms, loop_interval=args.interval)

    logger.info("\n[EXIT] Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())