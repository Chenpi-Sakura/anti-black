"""Apply Phase 2 SQL migrations.
Usage: conda run -n anti-black python scripts/apply_migrations.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config import get_config


def main():
    cfg = get_config()
    pg = cfg.postgresql
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
    )
    conn.autocommit = True
    cur = conn.cursor()

    migrations_dir = Path(__file__).parent.parent / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    print(f"Found {len(files)} migration file(s) in {migrations_dir}:")
    for f in files:
        print(f"  {f.name}")

    for f in files:
        print(f"\n[apply] {f.name}")
        sql = f.read_text(encoding='utf-8')
        try:
            cur.execute(sql)
            print(f"  OK")
        except Exception as e:
            print(f"  FAILED: {e}")
            raise

    cur.close()
    conn.close()
    print("\n[done] All migrations applied.")


if __name__ == "__main__":
    main()
