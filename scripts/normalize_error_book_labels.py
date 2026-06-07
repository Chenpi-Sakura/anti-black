"""
One-shot backfill: normalize error_book labels to 5 canonical Chinese strings.

After deploy of error_book_sampler.py changes (prompt + normalize on
write/read), existing error_book rows from before the fix still have
polluted labels like '账号交易 (Account Trading)' or '未知/其他
(Unknown/Other)'. This script re-derives them to the 5 canonical
forms using ILIKE pattern matching. Mirrors the pattern in
scripts/normalize_clue_labels.py.

Safe to re-run (idempotent -- second pass matches no rows).

Usage:
  python scripts/normalize_error_book_labels.py            # dry-run
  python scripts/normalize_error_book_labels.py --apply    # execute
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2


CANONICAL_LABELS = ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "192.168.148.128"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "antiblack"),
        password=os.environ.get("POSTGRES_PASSWORD", "antiblack123"),
        dbname=os.environ.get("POSTGRES_DATABASE", "antiblack"),
    )


def normalize_sql(field: str) -> str:
    """Build the CASE expression to map a polluted label back to 5 canonical.

    BUG-FIX (2026-06-07): ELSE branch was silently re-bucketing unknown
    strings into '未知/其他', masking genuinely-broken labels. Now: if
    the value doesn't match one of the 4 known patterns, set NULL
    (which downstream collect_error_samples will skip via the
    Classifier._normalize_level1_label fallback to '未知/其他'). The
    pre-update distribution report on the polluted-value SELECT will
    surface the count of unmatched rows for human review.
    """
    return f"""
    CASE
        WHEN {field} ILIKE '%账号交易%' OR {field} ILIKE '%Account Trading%' THEN '账号交易'
        WHEN {field} ILIKE '%流量作弊%' OR {field} ILIKE '%Traffic Cheating%' THEN '流量作弊'
        WHEN {field} ILIKE '%诈骗引流%' OR {field} ILIKE '%Fraud Leads%' THEN '诈骗引流'
        WHEN {field} ILIKE '%黑产工具%' OR {field} ILIKE '%Black-market%' OR {field} ILIKE '%Black Market%' THEN '黑产工具'
        WHEN {field} ILIKE '%未知%' OR {field} ILIKE '%Unknown%' OR {field} ILIKE '%其他%' OR {field} ILIKE '%未分类%' THEN '未知/其他'
        ELSE NULL
    END
    """


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute the UPDATE (default is dry-run)")
    parser.add_argument("--schema", default="antiblack")
    args = parser.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Preview: show distribution of polluted labels
        cur.execute(
            f"SELECT llm_label, count(*) FROM {args.schema}.error_book "
            f"WHERE llm_label IS NOT NULL AND llm_label NOT IN %s GROUP BY llm_label ORDER BY 2 DESC",
            (CANONICAL_LABELS,),
        )
        print("[normalize_error_book_labels] polluted llm_label values:")
        polluted = cur.fetchall()
        if not polluted:
            print("  (none — all labels already canonical)")
        else:
            total = sum(n for _, n in polluted)
            for label, n in polluted[:20]:
                print(f"  {label!r}: {n}")
            print(f"  total polluted: {total}")

        cur.execute(
            f"SELECT original_label, count(*) FROM {args.schema}.error_book "
            f"WHERE original_label IS NOT NULL AND original_label NOT IN %s GROUP BY original_label ORDER BY 2 DESC",
            (CANONICAL_LABELS,),
        )
        print("[normalize_error_book_labels] polluted original_label values:")
        polluted_orig = cur.fetchall()
        if not polluted_orig:
            print("  (none — all labels already canonical)")
        else:
            total = sum(n for _, n in polluted_orig)
            for label, n in polluted_orig[:20]:
                print(f"  {label!r}: {n}")
            print(f"  total polluted: {total}")

        # Build UPDATEs — only touch rows that have a polluted label
        # (anything outside the 5 canonical strings).
        update_llm = (
            f"UPDATE {args.schema}.error_book "
            f"SET llm_label = {normalize_sql('llm_label')} "
            f"WHERE llm_label IS NOT NULL AND llm_label NOT IN %s"
        )
        update_orig = (
            f"UPDATE {args.schema}.error_book "
            f"SET original_label = {normalize_sql('original_label')} "
            f"WHERE original_label IS NOT NULL AND original_label NOT IN %s"
        )

        if not args.apply:
            conn.rollback()
            print("[normalize_error_book_labels] DRY-RUN: no changes made")
            return

        cur.execute(update_llm, (CANONICAL_LABELS,))
        n_llm = cur.rowcount
        cur.execute(update_orig, (CANONICAL_LABELS,))
        n_orig = cur.rowcount
        conn.commit()
        print(f"[normalize_error_book_labels] APPLIED: llm_label updated {n_llm} rows, "
              f"original_label updated {n_orig} rows")

        # Verify post-state
        cur.execute(
            f"SELECT llm_label, count(*) FROM {args.schema}.error_book "
            f"WHERE llm_label IS NOT NULL GROUP BY llm_label ORDER BY 2 DESC"
        )
        print("[normalize_error_book_labels] post-update llm_label distribution:")
        for label, n in cur.fetchall():
            print(f"  {label}: {n}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
