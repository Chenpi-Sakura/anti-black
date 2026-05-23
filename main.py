"""
AntiBlack - 黑灰产情报分析Agent系统
Main entry point for the application.
"""
import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_config


def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/antiblack.log')
        ]
    )


def create_log_directory():
    """Create log directory if it doesn't exist."""
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)


def main():
    """Main entry point."""
    create_log_directory()
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("Starting AntiBlack System...")

    try:
        config = get_config()
        logger.info(f"Loaded configuration for {config.app.name} v{config.app.version}")

        # Run the Flask server
        from api.server import app
        logger.info(f"Starting API server on {config.app.host}:{config.app.port}")

        app.run(
            host=config.app.host,
            port=config.app.port,
            debug=config.app.debug
        )
    except Exception as e:
        logger.error(f"Failed to start system: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()