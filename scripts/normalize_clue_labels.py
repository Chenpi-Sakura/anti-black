"""
历史数据清洗：把 clues 表中所有非标准的 risk_label_level1 归一化为 5 个标准值。
Usage: conda run -n anti-black python scripts/normalize_clue_labels.py [--commit|--rollback|--dryrun]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from config import get_config


STANDARD_LABELS = ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')


def normalize_sql(field: str) -> str:
    """Build the CASE expression that normalizes a label field."""
    return f"""
        CASE
            WHEN {field} ILIKE '%账号交易%' OR {field} ILIKE '%Account Trading%' THEN '账号交易'
            WHEN {field} ILIKE '%流量作弊%' OR {field} ILIKE '%Traffic Cheating%' THEN '流量作弊'
            WHEN {field} ILIKE '%诈骗引流%' OR {field} ILIKE '%Fraud Leads%' THEN '诈骗引流'
            WHEN {field} ILIKE '%黑产工具%' OR {field} ILIKE '%Black-market Tools%' OR {field} ILIKE '%Blackmarket Tools%' THEN '黑产工具'
            ELSE '未知/其他'
        END
    """


def main():
    parser = argparse.ArgumentParser(description='Normalize clues.risk_label_level1 to 5 standard values')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--commit', action='store_true', help='Apply UPDATE (requires --yes)')
    group.add_argument('--dryrun', action='store_true', help='Preview only, default')
    group.add_argument('--rollback', action='store_true', help='Restore the snapshot taken during the last --commit')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt on --commit')
    args = parser.parse_args()

    cfg = get_config()
    pg = cfg.postgresql
    schema = "antiblack"

    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Step 1: Preview the work
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE risk_label_level1 NOT IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')
                ) AS dirty_count,
                COUNT(*) AS total_count
            FROM {schema}.clues
        """)
        row = cur.fetchone()
        dirty = row['dirty_count']
        total = row['total_count']
        print(f"[preview] {dirty} of {total} rows have non-standard labels ({dirty*100/max(total,1):.1f}%)")

        if dirty == 0:
            print("[preview] Nothing to do.")
            return

        cur.execute(f"""
            SELECT risk_label_level1 AS old_label,
                   {normalize_sql('risk_label_level1')} AS new_label,
                   COUNT(*) AS cnt
            FROM {schema}.clues
            WHERE risk_label_level1 NOT IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')
            GROUP BY risk_label_level1
            ORDER BY cnt DESC
        """)
        plan = cur.fetchall()
        print("\n[preview] Conversion plan:")
        print(f"  {'old_label':<40} {'new_label':<12} {'count':>6}")
        print("  " + "-" * 62)
        for r in plan:
            print(f"  {r['old_label']:<40} {r['new_label']:<12} {r['cnt']:>6}")

        # Step 2: Apply or dry-run
        if args.rollback:
            cur.execute(f"""
                SELECT COUNT(*) AS cnt FROM {schema}.clues_label_snapshot
                WHERE created_at = (SELECT MAX(created_at) FROM {schema}.clues_label_snapshot)
            """)
            snap = cur.fetchone()
            if not snap or snap['cnt'] == 0:
                print("[rollback] No snapshot found. Aborting.")
                return
            cur.execute(f"""
                UPDATE {schema}.clues c
                SET risk_label_level1 = s.old_label
                FROM {schema}.clues_label_snapshot s
                WHERE c.clue_id = s.clue_id
                  AND s.created_at = (SELECT MAX(created_at) FROM {schema}.clues_label_snapshot)
            """)
            print(f"[rollback] Restored {cur.rowcount} rows from snapshot.")
            conn.commit()
            return

        if not args.commit:
            print("\n[dryrun] No changes applied. Pass --commit --yes to apply.")
            return

        if not args.yes:
            resp = input(f"\n[commit] About to UPDATE {dirty} rows. Proceed? [yes/no]: ")
            if resp.strip().lower() != 'yes':
                print("[commit] Aborted.")
                return

        # Take a snapshot first
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.clues_label_snapshot (
                clue_id VARCHAR(255) PRIMARY KEY,
                old_label TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute(f"TRUNCATE {schema}.clues_label_snapshot")
        cur.execute(f"""
            INSERT INTO {schema}.clues_label_snapshot (clue_id, old_label)
            SELECT clue_id, risk_label_level1
            FROM {schema}.clues
            WHERE risk_label_level1 NOT IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')
        """)
        snap_count = cur.rowcount
        print(f"[commit] Snapshot saved: {snap_count} rows in clues_label_snapshot")

        # Apply the UPDATE
        cur.execute(f"""
            UPDATE {schema}.clues
            SET risk_label_level1 = {normalize_sql('risk_label_level1')}
            WHERE risk_label_level1 NOT IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')
        """)
        affected = cur.rowcount
        print(f"[commit] UPDATE affected {affected} rows")

        if affected != dirty:
            print(f"[commit] WARNING: expected {dirty}, got {affected}. Rolling back.")
            conn.rollback()
            return

        # Show post-state distribution
        cur.execute(f"""
            SELECT risk_label_level1, COUNT(*) AS cnt
            FROM {schema}.clues
            GROUP BY risk_label_level1
            ORDER BY cnt DESC
        """)
        dist = cur.fetchall()
        print("\n[commit] Post-update distribution:")
        for r in dist:
            marker = "" if r['risk_label_level1'] in STANDARD_LABELS else "  *** DIRTY"
            print(f"  {r['risk_label_level1']:<40} {r['cnt']:>6}{marker}")

        conn.commit()
        print("\n[commit] COMMIT successful. Use --rollback to revert.")
    except Exception as e:
        conn.rollback()
        print(f"[error] {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
