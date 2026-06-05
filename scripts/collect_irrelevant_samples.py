"""收集负样本 (irrelevant samples) 用于训练 open-set classifier.

策略: 选取 risk_label_level1='未知/其他' 且 confidence 较低的历史样本, 这些大概率是普通内容/广告/噪声.
按 cleaned_text 去重, 写入 antiblack.irrelevant_samples 表.

用法:
    python scripts/collect_irrelevant_samples.py [--limit N] [--min-conf 0.0] [--max-conf 0.5]
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from config import get_config


def main():
    parser = argparse.ArgumentParser(description='Collect irrelevant samples for open-set training')
    parser.add_argument('--limit', type=int, default=2000, help='Max samples to insert')
    parser.add_argument('--max-conf', type=float, default=0.5, help='Upper bound on confidence')
    parser.add_argument('--dryrun', action='store_true', help='Preview only')
    parser.add_argument('--commit', action='store_true', help='Insert into DB')
    args = parser.parse_args()

    cfg = get_config()
    pg = cfg.postgresql
    schema = "antiblack"
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Ensure the target table exists
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {schema}.irrelevant_samples (
            sample_id     VARCHAR(64) PRIMARY KEY,
            clue_id       VARCHAR(255),
            cleaned_text  TEXT NOT NULL,
            source        VARCHAR(32),
            confidence    REAL,
            created_at    TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_irrelevant_text ON {schema}.irrelevant_samples (cleaned_text)")

    # Find candidate samples: 未知/其他 with low confidence, deduplicated by cleaned_text
    cur.execute(f"""
        WITH candidates AS (
            SELECT
                c.clue_id,
                c.cleaned_text,
                c.classification_source AS source,
                c.confidence,
                c.risk_label_level1,
                ROW_NUMBER() OVER (PARTITION BY c.cleaned_text ORDER BY c.confidence) AS rn
            FROM {schema}.clues c
            WHERE c.risk_label_level1 = '未知/其他'
              AND c.confidence <= %(max_conf)s
              AND c.cleaned_text IS NOT NULL
              AND LENGTH(c.cleaned_text) >= 8
              AND LENGTH(c.cleaned_text) <= 500
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.irrelevant_samples i
                  WHERE i.cleaned_text = c.cleaned_text
              )
        )
        SELECT * FROM candidates WHERE rn = 1
        ORDER BY confidence ASC
        LIMIT %(limit)s
    """, {'max_conf': args.max_conf, 'limit': args.limit})
    rows = cur.fetchall()
    print(f"[candidates] {len(rows)} new samples (max_conf={args.max_conf}, limit={args.limit})")

    if not rows:
        print("Nothing to insert.")
        return

    # Preview — write to file to avoid GBK codec issues with emoji in samples
    preview_path = Path(__file__).parent / "_irrelevant_samples_preview.txt"
    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(f"First 10 of {len(rows)} candidates (max_conf={args.max_conf}):\n")
        f.write("-" * 80 + "\n")
        for r in rows[:10]:
            f.write(f"  conf={r['confidence']:.3f} src={r['source']} | {r['cleaned_text'][:80]}\n")
    print(f"\n[preview] first 10 samples written to {preview_path.name}")

    if args.dryrun or not args.commit:
        print(f"\n[dryrun] no rows inserted. Pass --commit to apply.")
        return

    # Insert
    import uuid
    inserted = 0
    for r in rows:
        try:
            cur.execute(f"""
                INSERT INTO {schema}.irrelevant_samples
                    (sample_id, clue_id, cleaned_text, source, confidence)
                VALUES (%(sid)s, %(cid)s, %(txt)s, %(src)s, %(conf)s)
                ON CONFLICT (sample_id) DO NOTHING
            """, {
                'sid': f"irr_{uuid.uuid4().hex[:16]}",
                'cid': r['clue_id'],
                'txt': r['cleaned_text'],
                'src': r['source'],
                'conf': r['confidence'],
            })
            inserted += 1
        except Exception as e:
            print(f"  [skip] {r['clue_id']}: {e}")
    print(f"\n[commit] inserted {inserted} rows into antiblack.irrelevant_samples")

    # Final count
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {schema}.irrelevant_samples")
    cnt = cur.fetchone()['cnt']
    print(f"[stats] total irrelevant samples: {cnt}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
