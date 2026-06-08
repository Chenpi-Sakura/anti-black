"""One-shot backfill for Phase 1 UPSERT-missing-column aftermath.

After deploying the UPSERT fix that now writes reject_until/regex_pattern/
meaning/source_channel, existing rows have NULL in those columns
(because they were written before the fix). This script:

  1. CONFIRMED rows with NULL meaning -> revert to LIKELY so the next
     validation cycle re-derives meaning and regex_pattern.
  2. REJECTED rows with NULL reject_until -> arm with now+30d so the
     silence period takes effect immediately.

Safe to re-run (idempotent).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

conn = psycopg2.connect(
    host='192.168.148.128', port=5432,
    user='antiblack', password='antiblack123',
    dbname='antiblack',
)
cur = conn.cursor()

# 1) CONFIRMED -> LIKELY for re-validation
cur.execute('''
    SELECT count(*) FROM antiblack.slang_candidates
    WHERE status='CONFIRMED' AND (meaning IS NULL OR regex_pattern IS NULL)
''')
n_confirmed_null = cur.fetchone()[0]
print(f"[backfill] CONFIRMED with NULL meaning/regex: {n_confirmed_null}")

if n_confirmed_null > 0:
    cur.execute('''
        UPDATE antiblack.slang_candidates
        SET meaning=NULL, regex_pattern=NULL, status='LIKELY', updated_at=NOW()
        WHERE status='CONFIRMED' AND (meaning IS NULL OR regex_pattern IS NULL)
    ''')
    print(f"[backfill] demoted {cur.rowcount} CONFIRMED rows -> LIKELY")

# 2) REJECTED reject_until arm
cur.execute('''
    SELECT count(*) FROM antiblack.slang_candidates
    WHERE status='REJECTED' AND reject_until IS NULL
''')
n_rejected_null = cur.fetchone()[0]
print(f"[backfill] REJECTED with NULL reject_until: {n_rejected_null}")

if n_rejected_null > 0:
    cur.execute('''
        UPDATE antiblack.slang_candidates
        SET reject_until=NOW() + INTERVAL '30 days', updated_at=NOW()
        WHERE status='REJECTED' AND reject_until IS NULL
    ''')
    print(f"[backfill] armed {cur.rowcount} REJECTED rows with reject_until=now+30d")

conn.commit()

# 3) Verify
cur.execute('''
    SELECT
        (SELECT count(*) FROM antiblack.slang_candidates WHERE status='LIKELY') AS likely,
        (SELECT count(*) FROM antiblack.slang_candidates WHERE status='CONFIRMED'
            AND (meaning IS NULL OR regex_pattern IS NULL)) AS confirmed_null,
        (SELECT count(*) FROM antiblack.slang_candidates WHERE status='REJECTED'
            AND reject_until IS NULL) AS rejected_null
''')
likely, confirmed_null, rejected_null = cur.fetchone()
print(f"[backfill] post-state: LIKELY={likely}, CONFIRMED_with_null={confirmed_null}, REJECTED_with_null={rejected_null}")

cur.close()
conn.close()
