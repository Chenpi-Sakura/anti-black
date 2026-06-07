"""
One-shot backfill: clean LIKELY pool of high-frequency stopwords.

After deploy of `config/slang_stopwords.py` + the `_extract_words` /
`_check_state_transition` guards in `pipeline/slang_learning.py`,
existing LIKELY rows (26,793 in production as of 2026-06-07) are
already-accumulated stopwords that would still need LLM rejection
to clear. This script DELETEs them in one shot.

Safe to re-run (idempotent -- no rows to delete on second run).
Default --dryrun prints SQL without executing.

Usage:
  python scripts/cleanup_slang_stopwords.py            # dry-run
  python scripts/cleanup_slang_stopwords.py --apply    # execute
"""
import argparse
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.slang_stopwords import _STOPWORDS


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "192.168.148.128"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "antiblack"),
        password=os.environ.get("POSTGRES_PASSWORD", "antiblack123"),
        dbname=os.environ.get("POSTGRES_DATABASE", "antiblack"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute the DELETE (default is dry-run)")
    parser.add_argument("--schema", default="antiblack")
    args = parser.parse_args()

    stopword_list = sorted(_STOPWORDS)
    print(f"[cleanup_slang_stopwords] stopword count: {len(stopword_list)}")

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Preview: how many LIKELY rows match the stopword set?
        cur.execute(
            f"SELECT status, count(*) FROM {args.schema}.slang_candidates "
            f"WHERE candidate_word = ANY(%s) GROUP BY status",
            (stopword_list,),
        )
        print(f"[cleanup_slang_stopwords] pre-delete distribution (matched by stopword):")
        for status, n in cur.fetchall():
            print(f"  {status}: {n}")

        # Re-arm REJECTED silence for words that are stopwords (defense in depth —
        # even if some REJECTED rows have stale reject_until, this resets them).
        # The DELETE only targets LIKELY; REJECTED stopwords keep reject_until.
        delete_sql = (
            f"DELETE FROM {args.schema}.slang_candidates "
            f"WHERE status = 'LIKELY' "
            f"AND candidate_word = ANY(%s)"
        )

        if not args.apply:
            cur.execute(delete_sql + " RETURNING candidate_word", (stopword_list,))
            would_delete = [r[0] for r in cur.fetchall()]
            conn.rollback()
            print(f"[cleanup_slang_stopwords] DRY-RUN: would delete {len(would_delete)} LIKELY rows")
            if would_delete[:20]:
                print(f"  sample: {would_delete[:20]}")
            return

        # Apply
        cur.execute(delete_sql, (stopword_list,))
        deleted = cur.rowcount
        conn.commit()
        print(f"[cleanup_slang_stopwords] APPLIED: deleted {deleted} LIKELY rows")

        # Verify
        cur.execute(
            f"SELECT status, count(*) FROM {args.schema}.slang_candidates GROUP BY status ORDER BY status"
        )
        print(f"[cleanup_slang_stopwords] post-delete distribution (full):")
        for status, n in cur.fetchall():
            print(f"  {status}: {n}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
