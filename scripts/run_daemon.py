"""
AntiBlack Daemon Entry Point - 24/7 Background Patrol Service
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_config
from services.daemon_scheduler import DaemonScheduler

# Setup logging
log_file = "./logs/antiblack_daemon.log"
os.makedirs(os.path.dirname(log_file), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the daemon."""
    logger.info("=" * 60)
    logger.info("AntiBlack Daemon v1.0")
    logger.info("24/7 Background Patrol Service")
    logger.info("=" * 60)

    # Load configuration
    config = get_config()

    # Check if daemon is enabled
    daemon_config = config.get('daemon', {})
    if not daemon_config.get('enabled', True):
        logger.info("Daemon is disabled in configuration")
        return

    # Create scheduler
    scheduler = DaemonScheduler(config)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        asyncio.create_task(scheduler.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        # Start daemon
        await scheduler.start()

        # Keep running until stopped
        logger.info("Daemon is running. Press Ctrl+C to stop.")
        while scheduler._running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Daemon error: {e}", exc_info=True)
    finally:
        if scheduler._running:
            await scheduler.stop()

    logger.info("Daemon shutdown complete")


if __name__ == '__main__':
    asyncio.run(main())
