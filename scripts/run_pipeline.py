"""
Run the full AntiBlack pipeline end-to-end.
Polls data from MediaCrawler, processes through cleaner/classifier/extractor/router.
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.media_crawler_adapter import MediaCrawlerAdapter
from pipeline.cleaner import Cleaner
from pipeline.classifier import Classifier
from pipeline.extractor import Extractor
from pipeline.router import Router
from pipeline.slang_learning import SlangLearner
from services.lightrag_service import GraphProcessor
from config import get_config
from services.database import PostgreSQLService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    config = get_config()
    logger.info("=" * 60)
    logger.info("Starting AntiBlack Pipeline Demo")
    logger.info("=" * 60)

    # Step 1: Initialize components
    logger.info("\n[Step 1] Initializing components...")

    # Initialize PostgreSQL service for reading slang mappings
    pg_db = PostgreSQLService.get_instance()
    logger.info(f"PostgreSQL connected: {pg_db}")

    # Initialize MediaCrawler adapter
    adapter = MediaCrawlerAdapter(config)
    await adapter.initialize()
    logger.info("MediaCrawler adapter initialized")

    # Initialize pipeline components
    cleaner = Cleaner()
    classifier = Classifier()
    extractor = Extractor()
    router = Router()

    logger.info("All pipeline components initialized")

    # Step 2: Poll data from MediaCrawler
    logger.info("\n[Step 2] Polling data from MediaCrawler...")

    # Poll Douyin content
    douyin_messages = await adapter.poll_new_content('douyin')
    logger.info(f"Polled {len(douyin_messages)} Douyin videos")

    # Poll Tieba content
    tieba_messages = await adapter.poll_new_content('tieba')
    logger.info(f"Polled {len(tieba_messages)} Tieba posts")

    all_messages = douyin_messages + tieba_messages
    if not all_messages:
        logger.warning("No messages polled! Check if MediaCrawler has data with matching keywords.")
        logger.info("Fallback: Testing with mock data")
        all_messages = [
            {
                "message_id": "test_001",
                "source_channel": "douyin",
                "group_id": "test",
                "author_id": "user_001",
                "raw_text": "出抖号，千粉，换绑稳，加V:dyhao668",
                "published_at": "2026-05-25T10:00:00+08:00",
                "metadata": {"platform": "douyin"}
            },
            {
                "message_id": "test_002",
                "source_channel": "baidu_tieba",
                "group_id": "test",
                "author_id": "user_002",
                "raw_text": "专业刷粉，价格优惠，微信:brushdan001",
                "published_at": "2026-05-25T10:05:00+08:00",
                "metadata": {"platform": "baidu_tieba"}
            },
            {
                "message_id": "test_003",
                "source_channel": "douyin",
                "group_id": "test",
                "author_id": "user_003",
                "raw_text": "接码平台新开，联系电话13800138000",
                "published_at": "2026-05-25T10:10:00+08:00",
                "metadata": {"platform": "douyin"}
            }
        ]

    # Step 3: Clean messages
    logger.info("\n[Step 3] Cleaning messages...")
    cleaned_messages = cleaner.clean(all_messages)
    logger.info(f"Cleaned {len(cleaned_messages)} messages (filtered {len(all_messages) - len(cleaned_messages)} noise messages)")

    # Step 4: Classify messages
    logger.info("\n[Step 4] Classifying messages...")
    classification_results = []
    for msg in cleaned_messages:
        result = classifier.classify(msg.cleaned_text, {"source_channel": msg.source_channel})
        classification_results.append(result)
        logger.info(f"  [{msg.message_id}] {result.level1_label}/{result.level2_label} (conf={result.confidence:.2f}) - {result.reason[:50]}...")

    # Step 5: Extract entities
    logger.info("\n[Step 5] Extracting entities...")
    extraction_results = []
    for i, msg in enumerate(cleaned_messages):
        result = extractor.extract(msg.message_id, msg.cleaned_text)
        extraction_results.append(result)
        entity_types = [e.entity_type for e in result.entities]
        logger.info(f"  [{msg.message_id}] entities={entity_types}, slang={[s.slang for s in result.slang_mappings]}")

    # Step 6: Route messages
    logger.info("\n[Step 6] Routing messages...")
    route_results = []
    for i, msg in enumerate(cleaned_messages):
        # Build message context for routing
        msg_context = {
            "message_id": msg.message_id,
            "source_channel": msg.source_channel,
            "risk_level": classification_results[i].level1_label,
            "entities": [{"type": e.entity_type} for e in extraction_results[i].entities],
            "slang_mappings": [{"slang": s.slang} for s in extraction_results[i].slang_mappings],
            "raw_text": msg.original_text,
            "cleaned_text": msg.cleaned_text,
        }
        channel = router.route(msg_context)
        route_results.append(channel)
        logger.info(f"  [{msg.message_id}] -> {channel} channel")

    # Step 7: Summary
    logger.info("\n" + "=" * 60)
    logger.info("Pipeline Summary")
    logger.info("=" * 60)
    logger.info(f"Total messages processed: {len(all_messages)}")
    logger.info(f"After cleaning: {len(cleaned_messages)}")

    level1_counts = {}
    for r in classification_results:
        level1_counts[r.level1_label] = level1_counts.get(r.level1_label, 0) + 1
    logger.info(f"Classification breakdown: {level1_counts}")

    channel_counts = {}
    for c in route_results:
        channel_counts[c] = channel_counts.get(c, 0) + 1
    logger.info(f"Routing breakdown: {channel_counts}")

    # Step 7: Process deep channel messages through LightRAG
    deep_messages = [msg for msg, channel in zip(cleaned_messages, route_results) if channel == 'deep']
    if deep_messages:
        logger.info(f"\n[Step 7] Processing {len(deep_messages)} messages through LightRAG...")
        graph_processor = GraphProcessor(config)
        await graph_processor.initialize()
        for i, msg in enumerate(cleaned_messages):
            if route_results[i] == 'deep':
                await graph_processor.process_message({
                    "message_id": msg.message_id,
                    "raw_text": msg.original_text,
                    "cleaned_text": msg.cleaned_text,
                    "classification": {
                        "level1_label": classification_results[i].level1_label,
                        "level2_label": classification_results[i].level2_label
                    },
                    "entities": []
                })
        await graph_processor.finalize()
        logger.info(f"LightRAG processing completed")
    else:
        logger.info("\n[Step 7] No deep channel messages to process")

    # Step 8: Slang learning (evolution)
    logger.info("\n[Step 8] Running slang learning...")
    slang_learner = SlangLearner(config)
    for msg in cleaned_messages:
        slang_learner.process_text(msg.cleaned_text, source_channel=msg.source_channel)

    # 验证 LIKELY 候选词
    confirmed = await slang_learner.validate_pending_candidates()
    if confirmed:
        logger.info(f"LLM validated {len(confirmed)} new CONFIRMED slang")

    stats = slang_learner.get_candidate_stats()
    logger.info(f"Slang learning stats: {stats}")

    # Cleanup
    await adapter.finalize()
    logger.info("\nPipeline completed successfully!")


if __name__ == '__main__':
    asyncio.run(main())