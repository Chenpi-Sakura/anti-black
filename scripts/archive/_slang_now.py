"""Check current slang learning state."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
from psycopg2.extras import RealDictCursor

out = []
def p(s=''): out.append(s)

conn = psycopg2.connect(host='192.168.148.128', port=5432, user='antiblack', password='antiblack123', dbname='antiblack', cursor_factory=RealDictCursor)
cur = conn.cursor()

# 1) State distribution
p('=== Slang state distribution (full) ===')
cur.execute('SELECT status, count(*) AS n FROM antiblack.slang_candidates GROUP BY 1 ORDER BY 1')
for r in cur.fetchall():
    p(f'  {r["status"]:>10}: {r["n"]:>6}')

# 2) LIKELY count buckets
p()
p('=== LIKELY occurrence_count distribution ===')
cur.execute('''
    SELECT
        CASE
            WHEN occurrence_count >= 50 THEN '>= 50 (eligible for LLM validation)'
            WHEN occurrence_count >= 30 THEN '30-49 (eligible NOW with new threshold)'
            WHEN occurrence_count >= 20 THEN '20-29 (just hit LIKELY)'
            ELSE '< 20'
        END AS bucket, count(*) AS n
    FROM antiblack.slang_candidates WHERE status = 'LIKELY'
    GROUP BY 1 ORDER BY 1
''')
for r in cur.fetchall():
    p(f'  {r["bucket"]:>50}: {r["n"]:>6}')

# 3) Recently CONFIRMED
p()
p('=== Recently CONFIRMED (last 30 min) ===')
cur.execute('''
    SELECT candidate_word, occurrence_count, meaning, updated_at
    FROM antiblack.slang_candidates
    WHERE status = 'CONFIRMED'
      AND updated_at > NOW() - INTERVAL '30 minutes'
    ORDER BY updated_at DESC LIMIT 20
''')
rows = cur.fetchall()
if not rows:
    p('  (no new CONFIRMED in last 30 min)')
for r in rows:
    m = (r['meaning'] or '')[:40]
    p(f'  [{r["updated_at"]:%H:%M}] n={r["occurrence_count"]:>3}  {r["candidate_word"]:>20}  {m!r}')

# 4) New CONFIRMED vs old CONFIRMED total
p()
p('=== CONFIRMED total ===')
cur.execute("SELECT count(*) AS n FROM antiblack.slang_candidates WHERE status='CONFIRMED'")
total = cur.fetchone()['n']
p(f'  total CONFIRMED in DB: {total}')

# 5) REJECTED reject_until
p()
p('=== REJECTED reject_until status ===')
cur.execute('''
    SELECT
        count(*) FILTER (WHERE reject_until IS NULL) AS null_until,
        count(*) FILTER (WHERE reject_until IS NOT NULL AND reject_until > NOW()) AS armed,
        count(*) FILTER (WHERE reject_until IS NOT NULL AND reject_until <= NOW()) AS expired,
        count(*) AS total
    FROM antiblack.slang_candidates WHERE status = 'REJECTED'
''')
r = cur.fetchone()
p(f'  null: {r["null_until"]} | armed (in future): {r["armed"]} | expired: {r["expired"]} | total: {r["total"]}')

# 6) Top LIKELY (real slangs closest to validation)
p()
p('=== Top 20 LIKELY by count (real slangs near validation gate) ===')
cur.execute('''
    SELECT candidate_word, occurrence_count
    FROM antiblack.slang_candidates
    WHERE status = 'LIKELY'
    ORDER BY occurrence_count DESC LIMIT 20
''')
for r in cur.fetchall():
    p(f'  n={r["occurrence_count"]:>3}  {r["candidate_word"]:>25}')

# 7) Validation tick rate from daemon log
p()
p('=== Daemon log validation activity (last 20 lines) ===')
import subprocess
try:
    result = subprocess.run(
        ['tail', '-100', 'D:/Projects/ByteDance/anti-black/daemon.out.log'],
        capture_output=True, text=True, timeout=5
    )
    lines = result.stdout.splitlines()
    relevant = [l for l in lines if 'validation' in l.lower() or 'CONFIRMED' in l or 'inconsistency' in l.lower() or 'Slang learning' in l]
    for l in relevant[-15:]:
        p(f'  {l[:150]}')
except Exception as e:
    p(f'  (log read failed: {e})')

cur.close(); conn.close()

out_path = os.path.join(os.path.dirname(__file__), "_slang_now.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"WROTE {out_path}")
