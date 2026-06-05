"""
诊断脚本：分析训练数据分布和分类质量
Usage: conda run -n anti-black python scripts/diagnose_training_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from config import get_config


def run_queries():
    cfg = get_config()
    pg = cfg.postgresql

    conn = psycopg2.connect(
        host=pg.host,
        port=pg.port,
        user=pg.user,
        password=pg.password,
        database=pg.database,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    schema = "antiblack"

    queries = {
        "clues_overview": f"""
            SELECT
                risk_label_level1,
                risk_label_level2,
                COUNT(*) AS cnt,
                ROUND(AVG(confidence)::numeric, 3) AS avg_conf,
                ROUND(MIN(confidence)::numeric, 3) AS min_conf,
                ROUND(MAX(confidence)::numeric, 3) AS max_conf
            FROM {schema}.clues
            GROUP BY risk_label_level1, risk_label_level2
            ORDER BY cnt DESC;
        """,
        "clues_by_source": f"""
            SELECT
                classification_source,
                COUNT(*) AS cnt,
                ROUND(AVG(confidence)::numeric, 3) AS avg_conf
            FROM {schema}.clues
            GROUP BY classification_source
            ORDER BY cnt DESC;
        """,
        "confidence_distribution": f"""
            SELECT
                CASE
                    WHEN confidence >= 0.9 THEN '0.9+'
                    WHEN confidence >= 0.8 THEN '0.8-0.9'
                    WHEN confidence >= 0.7 THEN '0.7-0.8'
                    WHEN confidence >= 0.6 THEN '0.6-0.7'
                    WHEN confidence >= 0.5 THEN '0.5-0.6'
                    ELSE '<0.5'
                END AS bucket,
                COUNT(*) AS cnt
            FROM {schema}.clues
            GROUP BY 1
            ORDER BY 1;
        """,
        "silver_candidates": f"""
            SELECT
                risk_label_level1,
                COUNT(*) AS silver_cnt
            FROM {schema}.clues c
            LEFT JOIN {schema}.feedback f ON c.clue_id = f.clue_id
            WHERE c.confidence >= 0.8 AND f.feedback_id IS NULL
            GROUP BY risk_label_level1
            ORDER BY silver_cnt DESC;
        """,
        "feedback_overview": f"""
            SELECT
                COUNT(*) AS total_feedback,
                SUM(CASE WHEN platinum_enrolled THEN 1 ELSE 0 END) AS platinum_cnt,
                COUNT(DISTINCT correct_risk_label_level1) AS distinct_correct_labels
            FROM {schema}.feedback;
        """,
        "feedback_labels": f"""
            SELECT
                correct_risk_label_level1,
                COUNT(*) AS cnt,
                SUM(CASE WHEN platinum_enrolled THEN 1 ELSE 0 END) AS platinum_cnt
            FROM {schema}.feedback
            GROUP BY correct_risk_label_level1
            ORDER BY cnt DESC;
        """,
        "recent_clues_trend": f"""
            SELECT
                DATE_TRUNC('day', created_at) AS day,
                COUNT(*) AS cnt,
                ROUND(AVG(confidence)::numeric, 3) AS avg_conf
            FROM {schema}.clues
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY 1
            ORDER BY 1 DESC;
        """,
    }

    for name, sql in queries.items():
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print("=" * 60)
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            if not rows:
                print("  (no data)")
                continue
            # Print header
            keys = list(rows[0].keys())
            header = " | ".join(f"{k:18}" for k in keys)
            print(f"  {header}")
            print(f"  {'-' * len(header)}")
            for row in rows:
                line = " | ".join(f"{str(v):18}" for v in row.values())
                print(f"  {line}")

    conn.close()
    print(f"\n{'=' * 60}")
    print("  Done")
    print("=" * 60)


if __name__ == "__main__":
    run_queries()
