#!/usr/bin/env python3
"""
Migrate V4 reclassified clues to training_samples as silver labels.

V4 reclassify_unknown.py writes back to clues table directly without
inserting into training_samples. This script bridges that gap so
daemon's _retrain_check_loop will see them as new silver samples.

Filter: clues where classification_reason starts with 'V4 ' (V4 rule
reclassify or V4 LLM reclassify) AND confidence >= 0.7. Lower
threshold than the 0.8 used in production because:
- V4 rule reclassify is exact-match (no confidence issue)
- V4 LLM reclassify has the canonical L2 validation guarantee

ON CONFLICT DO NOTHING on (sample_id) prevents duplicate inserts if
this script is run multiple times.

Idempotent: re-running adds 0 rows once migrated.

Usage:
    python scripts/migrate_v4_to_silver.py
    python scripts/migrate_v4_to_silver.py --min-confidence 0.5
"""
import argparse
import sys
import uuid
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.database import PostgreSQLService
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('migrate_v4_silver')


def fetch_v4_clues(db, min_confidence: float, batch: int) -> list:
    """Fetch clues reclassified by V4 with confidence >= threshold."""
    with db._get_cursor() as cur:
        cur.execute(
            """
            SELECT clue_id, risk_label_level1, risk_label_level2,
                   confidence, classification_reason
            FROM antiblack.clues
            WHERE classification_reason LIKE 'V4 %'
              AND confidence >= %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (min_confidence, batch),
        )
        return cur.fetchall()


def already_migrated_count(db) -> int:
    """Count V4-migration silver rows already in training_samples."""
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as cnt
            FROM antiblack.training_samples
            WHERE collection_context = 'v4_migration'
        """)
        return cur.fetchone()['cnt']


def insert_silver_batch(db, rows: list, min_confidence: float) -> int:
    """Insert V4-classified clues as silver training samples."""
    inserted = 0
    with db._get_cursor() as cur:
        for r in rows:
            sample_id = f"ts_{uuid.uuid4().hex[:16]}"
            try:
                cur.execute(
                    """
                    INSERT INTO antiblack.training_samples
                        (sample_id, text, label, label_source, confidence, collection_context, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (sample_id) DO NOTHING
                    """,
                    (
                        sample_id,
                        r['risk_label_level2'] or '',  # text column holds the level2 for traceability
                        r['risk_label_level1'],
                        'silver',
                        r['confidence'],
                        'v4_migration',
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.error(f"Insert failed for {r['clue_id']}: {e}")
                cur.connection.rollback()
                continue
        cur.connection.commit()
    return inserted


def main():
    p = argparse.ArgumentParser(description='Migrate V4-classified clues to training_samples (silver)')
    p.add_argument('--min-confidence', type=float, default=0.7,
                   help='Min confidence threshold (default: 0.7)')
    p.add_argument('--batch', type=int, default=10000,
                   help='Max clues to process per run (default: 10000)')
    args = p.parse_args()

    db = PostgreSQLService.get_instance()

    # 1. 现状查询
    logger.info("=" * 60)
    logger.info("V4 → training_samples migration")
    logger.info(f"  min confidence: {args.min_confidence}")
    logger.info(f"  batch size:     {args.batch}")
    logger.info("=" * 60)

    # 2. 已经迁移过的
    already = already_migrated_count(db)
    logger.info(f"Already migrated silver rows: {already}")

    # 3. 拉 V4 candidates
    rows = fetch_v4_clues(db, args.min_confidence, args.batch)
    logger.info(f"Found {len(rows)} V4-classified clues (conf >= {args.min_confidence})")
    if not rows:
        logger.info("Nothing to migrate.")
        return

    # 4. Sample distribution preview
    dist = {}
    for r in rows:
        key = f"{r['risk_label_level1']}/{r['risk_label_level2']}"
        dist[key] = dist.get(key, 0) + 1
    logger.info("Sample distribution preview:")
    for k in sorted(dist, key=lambda x: -dist[x]):
        logger.info(f"  {k}: {dist[k]}")

    # 5. Insert
    inserted = insert_silver_batch(db, rows, args.min_confidence)
    logger.info(f"Inserted {inserted}/{len(rows)} silver samples.")

    # 6. Verify
    after = already_migrated_count(db)
    logger.info(f"Total silver rows after migration: {after}")


if __name__ == '__main__':
    main()
