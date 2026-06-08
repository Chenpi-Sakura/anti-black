"""
Apply stopword audit results: register_stopword() + DELETE from slang_candidates.

Reads scripts/audit_stopword_results.json, filters to llm_verdict='stopword'
with confidence >= threshold, then for each word:
  1. register_stopword(word)        - persists to data/stopword_register.json
                                     (mtime change triggers daemon auto-reload)
  2. time.sleep(1.5)                - race window: give daemon 1.5s to notice
                                     mtime change and reload Set on its next
                                     is_stopword() call before we DELETE the DB row
  3. DELETE FROM slang_candidates   - unified regardless of original status
                                     (LIKELY/OBSERVED/NEW all just need to go;
                                     the ingest side now blocks re-creation)

Dry-run by default (project convention 2026-06-07 Pattern A).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2

# Import after sys.path setup so the package resolves
from config.slang_stopwords import register_stopword


DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "192.168.148.128"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": "antiblack",
    "password": "antiblack123",
    "database": "antiblack",
}

DEFAULT_INPUT = PROJECT_ROOT / "scripts" / "audit_stopword_results.json"
DEFAULT_MIN_CONFIDENCE = 80   # out of 100
RACE_WINDOW_SEC = 1.5         # daemon reload buffer (see plan critique 3)


def load_audit(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_to_apply(audit: dict, min_confidence: int) -> list:
    """Filter audit items to stopword + confidence >= threshold."""
    out = []
    for it in audit.get("items", []):
        if it.get("llm_verdict") == "stopword" and (it.get("confidence") or 0) >= min_confidence:
            out.append(it)
    return out


def pre_distribution(items: list, conn) -> dict:
    """Show pre-action status distribution for preview."""
    if not items:
        return {}
    cur = conn.cursor()
    cur.execute("""
        SELECT status, count(*)
        FROM antiblack.slang_candidates
        WHERE candidate_word = ANY(%s)
        GROUP BY status
    """, ([it["word"] for it in items],))
    return {row[0]: row[1] for row in cur.fetchall()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT),
                        help=f"Audit JSON (default {DEFAULT_INPUT.name})")
    parser.add_argument("--min-confidence", type=int, default=DEFAULT_MIN_CONFIDENCE,
                        help=f"Min LLM confidence 0-100 (default {DEFAULT_MIN_CONFIDENCE})")
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes (default is dry-run)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip 'Type apply' confirmation prompt")
    args = parser.parse_args()

    audit = load_audit(Path(args.input))
    to_apply = filter_to_apply(audit, args.min_confidence)

    print(f"[apply_stopword_audit] input: {args.input}")
    print(f"[apply_stopword_audit] min confidence: {args.min_confidence}")
    print(f"[apply_stopword_audit] stopword count to register: {len(to_apply)}")

    if not to_apply:
        print("[apply_stopword_audit] nothing to apply; exiting")
        return

    # Preview distribution
    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
    try:
        dist = pre_distribution(to_apply, conn)
        print(f"[apply_stopword_audit] pre-action distribution:")
        total = 0
        for status in ("LIKELY", "OBSERVED", "NEW", "CONFIRMED", "REJECTED", "STABLE"):
            n = dist.get(status, 0)
            total += n
            print(f"  {status:>10}: {n:>4} (will be deleted)")
        print(f"  {'total':>10}: {total:>4}")

        if not args.apply:
            print(f"[apply_stopword_audit] DRY-RUN: no changes written")
            print(f"[apply_stopword_audit] re-run with --apply to commit")
            return

        # Confirmation gate
        if not args.yes:
            try:
                confirm = input("Type 'apply' to commit: ")
            except EOFError:
                print("[apply_stopword_audit] no TTY; aborting (use --yes to skip)")
                return
            if confirm.strip() != "apply":
                print("[apply_stopword_audit] confirmation failed; aborting")
                return

        # Apply: for each word
        cur = conn.cursor()
        n_registered = 0
        n_deleted = 0
        for it in to_apply:
            word = it["word"]
            # Step 1: persist JSON (mtime bump triggers daemon reload)
            if register_stopword(word):
                n_registered += 1
            # Step 2: race window (1.5s) so daemon's next is_stopword()
            # call picks up the mtime change BEFORE we DELETE the row
            time.sleep(RACE_WINDOW_SEC)
            # Step 3: DELETE (unified regardless of original status)
            cur.execute(
                "DELETE FROM antiblack.slang_candidates WHERE candidate_word = %s",
                (word,),
            )
            n_deleted += cur.rowcount
        conn.commit()
        print(f"[apply_stopword_audit] APPLIED:")
        print(f"  registered to stopword_register.json: {n_registered}")
        print(f"  deleted from slang_candidates:         {n_deleted}")
        print(f"[apply_stopword_audit] daemon will auto-reload on next is_stopword() call (mtime check)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
