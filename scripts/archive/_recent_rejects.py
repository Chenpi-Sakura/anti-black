"""Check recently rejected candidates to see if real slangs are being killed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
from psycopg2.extras import RealDictCursor

out = []
def p(s=''): out.append(s)

conn = psycopg2.connect(host='192.168.148.128', port=5432, user='antiblack', password='antiblack123', dbname='antiblack', cursor_factory=RealDictCursor)
cur = conn.cursor()

# Most recent REJECTED (last 1h) - check if any of the previous top LIKELY are there
p('=== Most recent REJECTED (last 1h, top 30) ===')
cur.execute('''
    SELECT candidate_word, occurrence_count, reject_until, updated_at
    FROM antiblack.slang_candidates
    WHERE status = 'REJECTED'
      AND updated_at > NOW() - INTERVAL '1 hour'
    ORDER BY updated_at DESC LIMIT 30
''')
rows = cur.fetchall()
if not rows:
    p('  (none in last 1h)')
for r in rows:
    p(f'  [{r["updated_at"]:%H:%M}] n={r["occurrence_count"]:>3}  {r["candidate_word"]:>25}  reject_until={r["reject_until"]}')

# Count REJECTED added in last 1h
p()
p('=== REJECTED count delta (last 1h vs prior 1h) ===')
cur.execute('''
    SELECT
        (SELECT count(*) FROM antiblack.slang_candidates WHERE status='REJECTED' AND updated_at > NOW() - INTERVAL '1 hour') AS last_1h,
        (SELECT count(*) FROM antiblack.slang_candidates WHERE status='REJECTED' AND updated_at > NOW() - INTERVAL '2 hours' AND updated_at <= NOW() - INTERVAL '1 hour') AS prev_1h
''')
r = cur.fetchone()
p(f'  last 1h: {r["last_1h"]}, prior 1h: {r["prev_1h"]}, delta: +{r["last_1h"] - r["prev_1h"]}')

# Check daemon log for validation activity
p()
p('=== Daemon log slang validation (last 50 lines) ===')
import subprocess
try:
    result = subprocess.run(
        ['tail', '-100', 'D:/Projects/ByteDance/anti-black/daemon.out.log'],
        capture_output=True, text=True, timeout=5
    )
    lines = result.stdout.splitlines()
    relevant = [l for l in lines if any(kw in l for kw in ['CONFIRMED', 'validation', 'inconsistency', 'Slang evolution', 'Slang learning stats', 'no weak'])]
    for l in relevant[-20:]:
        p(f'  {l[:200]}')
except Exception as e:
    p(f'  (log read failed: {e})')

cur.close(); conn.close()

out_path = os.path.join(os.path.dirname(__file__), "_recent_rejects.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"WROTE {out_path}")
