"""Test MediaCrawlerAdapter - poll content from PostgreSQL via MediaCrawler."""
import asyncio
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_adapter_poll_douyin():
    """Test polling Douyin content from PostgreSQL."""
    import os
    import sys
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, PROJECT_ROOT)

    from config import get_config
    from pipeline.media_crawler_adapter import MediaCrawlerAdapter

    adapter_config = {
        'media_crawler': {
            'database': {
                'host': os.getenv('POSTGRES_HOST', '192.168.148.128'),
                'port': int(os.getenv('POSTGRES_PORT', 5432)),
                'user': os.getenv('POSTGRES_USER', 'antiblack'),
                'password': os.getenv('POSTGRES_PASSWORD', 'antiblack123'),
                'database': os.getenv('POSTGRES_DATABASE', 'antiblack'),
            }
        }
    }

    adapter = MediaCrawlerAdapter(adapter_config)
    await adapter.initialize()

    # Sync keywords
    keywords = await adapter.sync_keywords_from_slang_mapping()
    assert isinstance(keywords, list)

    # Poll content
    content = await adapter.poll_new_content('douyin')
    assert isinstance(content, list)

    await adapter.finalize()


@pytest.mark.asyncio
async def test_adapter_poll_tieba():
    """Test polling Tieba content from PostgreSQL."""
    import os
    import sys
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, PROJECT_ROOT)

    from config import get_config
    from pipeline.media_crawler_adapter import MediaCrawlerAdapter

    adapter_config = {
        'media_crawler': {
            'database': {
                'host': os.getenv('POSTGRES_HOST', '192.168.148.128'),
                'port': int(os.getenv('POSTGRES_PORT', 5432)),
                'user': os.getenv('POSTGRES_USER', 'antiblack'),
                'password': os.getenv('POSTGRES_PASSWORD', 'antiblack123'),
                'database': os.getenv('POSTGRES_DATABASE', 'antiblack'),
            }
        }
    }

    adapter = MediaCrawlerAdapter(adapter_config)
    await adapter.initialize()

    content = await adapter.poll_new_content('tieba')
    assert isinstance(content, list)

    await adapter.finalize()