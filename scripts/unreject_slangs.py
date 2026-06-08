"""
One-shot revival: un-REJECT recently-rejected slang candidates.

After dropping likely_to_confirmed 50->30->25, the LLM validator
started REJECTING real black-market slangs that had been sitting
in LIKELY at count 20-44. The 30-day silence period then locked
them out of the LIKELY queue.

This script revives candidates that:
  1. Were REJECTED in the last 24 hours (recent victim)
  2. Have occurrence_count >= 25 (the prior threshold floor)
  3. Match a curated allowlist of known-real slangs (or are LLM-
     audit-curated)

It sets status=LIKELY, reject_until=NULL, inference_count=0, so
the daemon's next validation cycle can re-evaluate them with the
new (more lenient) LLM prompt + log path.

CRITICAL: The 30-day silence was designed to prevent resurrection
loops. We deliberately override it here for KNOWN real slangs only
(the curated list). Randomly un-rejecting everything would defeat
the silence mechanism.

Usage:
  python scripts/unreject_slangs.py            # dry-run
  python scripts/unreject_slangs.py --apply    # execute
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2

# Curated allowlist of known real black-market slangs from the
# CONFIRMED/STABLE production history + LIKELY top-20 audit.
# Update this list when audit_stopword_candidates.py identifies
# new real slangs that the LLM has been wrongly rejecting.
KNOWN_REAL_SLANGS = {
    # From original 13 CONFIRMED (2026-06-07 audit)
    "邪修", "的来", "需要热度连西", "谁要此号", "万粉号",
    "有需要万粉号的吗", "出號", "换绑即可绝不找回", "实名已解",
    "音符千粉账号", "音符", "有没有出号的", "微信扩列",
    # From recent LIKELY top (n>=25)
    "专业服务", "游戏号怎么安全换", "粉星仔", "花式网名制作",
    "实名换绑", "出个", "出号", "收号", "要号", "号私",
    # Common known
    "加微", "代练", "刷单", "兼职", "加微💰", "出号吗",
}

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "192.168.148.128"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": "antiblack",
    "password": "antiblack123",
    "database": "antiblack",
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG, connect_timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Execute the UPDATE (default is dry-run)")
    parser.add_argument("--hours", type=int, default=24,
                        help="Only revive REJECTED within last N hours (default 24)")
    parser.add_argument("--min-occ", type=int, default=25,
                        help="Min occurrence_count to revive (default 25)")
    parser.add_argument("--schema", default="antiblack")
    parser.add_argument("--yes", action="store_true",
                        help="Skip 'Type apply' confirmation prompt (for scripted use)")
    args = parser.parse_args()

    # Build the in-list safely (hardcoded constants)
    in_list = "(" + ", ".join(f"'{w}'" for w in sorted(KNOWN_REAL_SLANGS)) + ")"

    # Write output to UTF-8 file (Windows GBK safe)
    out_path = PROJECT_ROOT / "scripts" / "_unreject_report.txt"
    out_lines = []
    def p(s=""):
        print(s)
        out_lines.append(s)

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Preview: what would be revived
        cur.execute(f"""
            SELECT candidate_word, occurrence_count, reject_until, updated_at
            FROM {args.schema}.slang_candidates
            WHERE status = 'REJECTED'
              AND updated_at > NOW() - (%(hours)s || ' hours')::INTERVAL
              AND occurrence_count >= %(min_occ)s
              AND candidate_word IN {in_list}
            ORDER BY occurrence_count DESC
        """, {"hours": str(args.hours), "min_occ": args.min_occ})
        rows = cur.fetchall()

        p(f"[unreject_slangs] filter: REJECTED in last {args.hours}h, occ >= {args.min_occ}, in curated allowlist ({len(KNOWN_REAL_SLANGS)} words)")
        p(f"[unreject_slangs] would revive {len(rows)} candidates:")
        for r in rows:
            p(f"  n={r[1]:>3}  {r[0]:>25}  reject_until={r[2]}  last_update={r[3]}")

        # Also: count how many REJECTED are not in allowlist (would be left alone)
        cur.execute(f"""
            SELECT count(*) FROM {args.schema}.slang_candidates
            WHERE status = 'REJECTED'
              AND updated_at > NOW() - (%(hours)s || ' hours')::INTERVAL
              AND occurrence_count >= %(min_occ)s
              AND candidate_word NOT IN {in_list}
        """, {"hours": str(args.hours), "min_occ": args.min_occ})
        not_in_allow = cur.fetchone()[0]
        p(f"[unreject_slangs] left alone (not in allowlist): {not_in_allow}")

        if not args.apply:
            p(f"[unreject_slangs] DRY-RUN: no changes written")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            return

        if not rows:
            p(f"[unreject_slangs] nothing to apply")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            return

        # Confirmation gate
        if not args.yes:
            try:
                confirm = input("Type 'apply' to commit: ")
            except EOFError:
                p("[unreject_slangs] no TTY; aborting (use --yes to skip)")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(out_lines))
                return
            if confirm.strip() != "apply":
                p("[unreject_slangs] confirmation failed; aborting")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(out_lines))
                return

        # Apply: reset to LIKELY with reject_until=NULL, inference_count=0.
        # Also reset regex_pattern to NULL so the validator generates a
        # fresh regex for the restored contexts.
        cur.execute(f"""
            UPDATE {args.schema}.slang_candidates
            SET status = 'LIKELY',
                reject_until = NULL,
                inference_count = 0,
                regex_pattern = NULL,
                updated_at = NOW()
            WHERE status = 'REJECTED'
              AND updated_at > NOW() - (%(hours)s || ' hours')::INTERVAL
              AND occurrence_count >= %(min_occ)s
              AND candidate_word IN {in_list}
        """, {"hours": str(args.hours), "min_occ": args.min_occ})
        n = cur.rowcount
        conn.commit()
        p(f"[unreject_slangs] APPLIED: revived {n} candidates -> LIKELY (reject_until=NULL, inference_count=0)")
        p(f"[unreject_slangs] daemon's next validation cycle will re-evaluate them with new code")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
