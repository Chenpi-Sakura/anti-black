"""
Cleanup script: demote non-slang words flagged by LLM audit.

Mirrors `pipeline.slang_learning.eliminate_weak_slangs()` cleanup pattern:
- PG: db.demote_slangs([word]) → UPDATE status='REJECTED' + DELETE slang_mappings
- PG: db.demote_seed_word([word]) → UPDATE seed_words
- LightRAG: graph_processor.delete_slang_entity(word) → remove entity
- TTL-aware blacklist: register_blacklist([word]) → adds to hardcoded blacklist
  with fresh 90d TTL, so resurrections are caught early (方案A 复活机制)

Safety:
- --dry-run: log only, no writes
- --backup: snapshot slang_mappings to backup table before first demote
- --yes: skip confirmation prompt
- --no-register-blacklist: do NOT add the demoted words to the hardcoded blacklist
  (use this if you want to re-audit these words manually later)
- Batch failures don't crash; errors logged and counted

Usage:
    # Preview (recommended first step)
    python scripts/cleanup_non_slangs.py --dry-run

    # Real run with backup, skip prompt, register to blacklist
    python scripts/cleanup_non_slangs.py --backup --yes

    # Real run, custom threshold and smaller batches
    python scripts/cleanup_non_slangs.py --confidence-threshold 90 --batch-size 25
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# === Output redirection for Windows GBK terminals ===
# Identical pattern to scripts/audit_slang_quality.py — every print() gets
# UTF-8-encoded to a tempfile (for grep/tail) and the original stdout stream
# is wrapped via a fresh instance to avoid recursion.
_log_path = os.path.join(tempfile.gettempdir(), "cleanup_non_slangs_output.txt")
_log_file = open(_log_path, "w", encoding="utf-8", errors="replace")


class _TeeStream:
    """Write to multiple streams; used to mirror print() into a UTF-8 tempfile."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for st in self._streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass

    def isatty(self):
        return False


# Replace stdout. The real terminal stream is opened separately to avoid
# infinite recursion (we can't reference sys.stdout inside its own replacement).
_real_stdout = sys.stdout
sys.stdout = _TeeStream(_log_file, _TeeStream(_real_stdout, _TeeStream(open(os.devnull, "w"))))

# === Project root ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2  # noqa: E402
from psycopg2 import sql  # noqa: E402

from config.slang_blacklist import register_blacklist  # noqa: E402

# === Config (mirrors scripts/audit_slang_quality.py) ===
DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "192.168.148.128"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": "antiblack",
    "password": "antiblack123",
    "database": "antiblack",
}

DEFAULT_INPUT = PROJECT_ROOT / "scripts" / "audit_slang_results.json"
DEFAULT_EXTRA_WORDS = ["三角洲租号", "内部代下", "和平精英租号", "账号"]
SCHEMA = "antiblack"
SILENCE_DAYS = 30  # Same as slang_learning.eliminate_weak_slangs()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_cleanup_words(input_path: Path, confidence_threshold: int) -> list:
    """Read JSON, filter to is_slang=false + conf>=threshold, return word list."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    flagged = [
        item["slang_raw"]
        for item in items
        if item.get("is_slang") is False
        and (item.get("confidence") or 0) >= confidence_threshold
    ]
    return flagged


def build_word_set(flagged_words: list, extra_words: list) -> list:
    """Merge flagged + extra, dedupe while preserving order."""
    seen = set()
    merged = []
    for w in flagged_words + extra_words:
        if w and w not in seen:
            seen.add(w)
            merged.append(w)
    return merged


# ---------------------------------------------------------------------------
# PG helpers (sync — matches audit_slang_quality.py style)
# ---------------------------------------------------------------------------

def create_backup_table(conn) -> str:
    """Snapshot slang_mappings to slang_mappings_backup_<timestamp>.

    Returns the backup table name.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"slang_mappings_backup_{ts}"
    with conn.cursor() as cur:
        cur.execute(sql.SQL(
            "CREATE TABLE {schema}.{tbl} AS "
            "SELECT * FROM {schema}.slang_mappings"
        ).format(
            schema=sql.Identifier(SCHEMA),
            tbl=sql.Identifier(backup_name),
        ))
    conn.commit()
    return backup_name


def demote_one_word_sync(conn, word: str) -> dict:
    """Demote a single word in PG: status=REJECTED + delete slang_mappings row.

    Returns a small dict with counts for logging.
    """
    reject_until = (datetime.utcnow() + __import__("datetime").timedelta(days=SILENCE_DAYS)).isoformat()

    with conn.cursor() as cur:
        # 1. Update slang_candidates → REJECTED (matches DB.demote_slangs)
        cur.execute(
            sql.SQL("""
                UPDATE {schema}.slang_candidates
                SET status = 'REJECTED', reject_until = %s, updated_at = NOW()
                WHERE candidate_word = %s
            """).format(schema=sql.Identifier(SCHEMA)),
            (reject_until, word),
        )
        cand_updated = cur.rowcount

        # 2. Hard-delete slang_mappings row (matches DB.demote_slangs)
        cur.execute(
            sql.SQL("""
                DELETE FROM {schema}.slang_mappings
                WHERE slang_raw = %s
            """).format(schema=sql.Identifier(SCHEMA)),
            (word,),
        )
        mapping_deleted = cur.rowcount

        # 3. Demote seed_words (source='learned' only, per DB.demote_seed_word invariant)
        cur.execute(
            sql.SQL("""
                UPDATE {schema}.seed_words
                SET status = 'degraded'
                WHERE source = 'learned' AND status = 'active' AND word = %s
            """).format(schema=sql.Identifier(SCHEMA)),
            (word,),
        )
        seed_updated = cur.rowcount

    conn.commit()
    return {
        "cand_updated": cand_updated,
        "mapping_deleted": mapping_deleted,
        "seed_updated": seed_updated,
    }


# ---------------------------------------------------------------------------
# LightRAG helpers (async)
# ---------------------------------------------------------------------------

async def delete_lightrag_entity(gp, word: str) -> bool:
    """Best-effort: delete a single entity from LightRAG. Return True if removed."""
    try:
        return bool(await gp.delete_slang_entity(word))
    except Exception as e:
        # Mirror eliminate_weak_slangs: LightRAG errors are warnings, not failures
        print(f"  [WARN] LightRAG delete failed for '{word}': {e}")
        return False


# ---------------------------------------------------------------------------
# Plan printing
# ---------------------------------------------------------------------------

def print_plan(words: list, batch_size: int, extra_words: list,
               confidence_threshold: int, dry_run: bool, backup: bool,
               register_to_blacklist: bool):
    """Print cleanup plan; sample of words; ask for confirmation if needed."""
    n = len(words)
    n_batches = (n + batch_size - 1) // batch_size
    print()
    print("=" * 72)
    print(f"  Cleanup plan (mode={'DRY-RUN' if dry_run else 'REAL EXECUTION'})")
    print("=" * 72)
    print(f"  Total words to demote:    {n}")
    print(f"  Confidence threshold:     >= {confidence_threshold}")
    print(f"  Batch size:               {batch_size}")
    print(f"  Number of batches:        {n_batches}")
    print(f"  Extra manual words:       {extra_words}")
    print(f"  Snapshot slang_mappings:  {backup}")
    print(f"  Silence days (REJECTED):  {SILENCE_DAYS}")
    print(f"  Register to blacklist:    {register_to_blacklist}  (TTL 90d, 方案A 复活机制)")
    print()
    print("  Sample of first 20 words to be removed:")
    for w in words[:20]:
        print(f"    - {w}")
    if n > 20:
        print(f"    ... and {n - 20} more")
    print()
    print("  Per-word operations:")
    print("    1. PG: UPDATE slang_candidates → status='REJECTED', reject_until=now+30d")
    print("    2. PG: DELETE FROM slang_mappings WHERE slang_raw = word")
    print("    3. PG: UPDATE seed_words SET status='degraded' WHERE source='learned' AND word=...")
    print("    4. LightRAG: graph_processor.delete_slang_entity(word)  (best-effort)")
    if register_to_blacklist:
        print("    5. config.slang_blacklist.register_blacklist([word])  (TTL 90d, persisted)")
    print("=" * 72)


def confirm_or_exit(skip_prompt: bool, dry_run: bool):
    """Single y/n prompt before first batch. Skip if --yes or --dry-run."""
    if skip_prompt or dry_run:
        if dry_run:
            print("  [DRY-RUN] no confirmation needed")
        else:
            print("  [AUTO] --yes set, skipping confirmation")
        return
    try:
        ans = input("Proceed with cleanup? [y/N]: ").strip().lower()
    except EOFError:
        print("  [AUTO] no TTY available, aborting")
        sys.exit(1)
    if ans != "y":
        print("Aborted by user.")
        sys.exit(0)
    print("Confirmed. Starting cleanup...")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_cleanup(words: list, batch_size: int, dry_run: bool, backup: bool,
                     register_to_blacklist: bool):
    """Run the actual cleanup (or just log in dry-run mode)."""
    n = len(words)
    n_batches = (n + batch_size - 1) // batch_size

    if dry_run:
        # In dry-run: open no DB connection, open no LightRAG, just log.
        for i, word in enumerate(words, 1):
            print(f"  [DRY-RUN] ({i}/{n}) would demote: {word}")
            if register_to_blacklist:
                print(f"  [DRY-RUN]   + would register to blacklist (TTL 90d): {word}")
        print()
        print("=" * 72)
        print(f"  [DRY-RUN] Summary: would demote {n} words, 0 errors")
        print(f"  [DRY-RUN] No DB writes, no LightRAG calls were made.")
        print("=" * 72)
        return

    # Real mode: open PG, optionally backup, then process.
    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
    print(f"Connected to PostgreSQL {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

    backup_name = None
    if backup:
        try:
            backup_name = create_backup_table(conn)
            print(f"  [BACKUP] Created {SCHEMA}.{backup_name} (snapshot of slang_mappings)")
        except Exception as e:
            print(f"  [ERROR] Backup failed: {e}. Aborting before any demote.")
            conn.close()
            sys.exit(2)

    # Initialize LightRAG once (mirrors eliminate_weak_slangs pattern)
    gp = None
    try:
        from services.lightrag_service import GraphProcessor
        from config import get_config
        gp = GraphProcessor(get_config())
        await gp.initialize()
        print("  [LightRAG] GraphProcessor initialized")
    except Exception as e:
        print(f"  [WARN] LightRAG init failed, will skip entity deletes: {e}")
        gp = None

    total_demoted = 0
    total_errors = 0
    total_registered = 0
    start = time.time()

    try:
        for batch_idx in range(n_batches):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, n)
            batch = words[batch_start:batch_end]
            batch_no = batch_idx + 1

            demoted = 0
            errors = 0
            registered = 0

            for word in batch:
                # 1+2+3: PG demote (sync)
                try:
                    demote_one_word_sync(conn, word)
                except Exception as e:
                    print(f"  [ERROR] PG demote failed for '{word}': {e}")
                    errors += 1
                    continue

                # 4: LightRAG entity delete (async, best-effort)
                if gp is not None:
                    if not await delete_lightrag_entity(gp, word):
                        # Not an error — entity may not exist in graph (newly added slang
                        # that never made it into LightRAG). Don't increment errors.
                        pass

                # 5: register to TTL-aware blacklist (方案A 复活机制)
                if register_to_blacklist:
                    try:
                        if register_blacklist([word]) > 0:
                            registered += 1
                    except Exception as e:
                        print(f"  [WARN] blacklist register failed for '{word}': {e}")
                        # Not a hard error — the word is already demoted in PG/LightRAG.

                demoted += 1

            total_demoted += demoted
            total_errors += errors
            total_registered += registered
            extra = f", {registered} registered" if register_to_blacklist else ""
            print(f"  batch {batch_no}/{n_batches} complete: {demoted} demoted, {errors} errors{extra}")
    finally:
        if gp is not None:
            try:
                await gp.finalize()
                print("  [LightRAG] GraphProcessor finalized")
            except Exception as e:
                print(f"  [WARN] LightRAG finalize failed: {e}")
        conn.close()
        print("  [PG] connection closed")

    elapsed = time.time() - start
    print()
    print("=" * 72)
    print(f"  Cleanup summary")
    print("=" * 72)
    print(f"  Total demoted:   {total_demoted} / {n}")
    print(f"  Total errors:    {total_errors}")
    if register_to_blacklist:
        print(f"  Total registered to blacklist (TTL 90d): {total_registered}")
    print(f"  Elapsed:         {elapsed:.2f}s")
    if backup_name:
        print(f"  Backup table:    {SCHEMA}.{backup_name}")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Demote non-slang words flagged by LLM audit (PG + LightRAG)."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help=f"Path to audit JSON (default: {DEFAULT_INPUT.name})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done; do NOT touch DB or LightRAG",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Process in batches of this size (default: 50)",
    )
    parser.add_argument(
        "--extra-words",
        type=str,
        default=",".join(DEFAULT_EXTRA_WORDS),
        help=(
            "Comma-separated extra words to clean "
            f"(default: {','.join(DEFAULT_EXTRA_WORDS)})"
        ),
    )
    parser.add_argument(
        "--confidence-threshold",
        type=int,
        default=80,
        help="Only clean LLM-flagged items with confidence >= this (default: 80)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help=(
            "Snapshot slang_mappings to slang_mappings_backup_<ts> "
            "BEFORE the first demote"
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the y/N confirmation prompt (use for cron/automation)",
    )
    parser.add_argument(
        "--no-register-blacklist",
        action="store_true",
        help=(
            "Do NOT add demoted words to the hardcoded blacklist (方案A). "
            "Use this if you want to re-audit these words manually later."
        ),
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        sys.exit(1)

    extra_words = [w.strip() for w in args.extra_words.split(",") if w.strip()]

    print(f"Loading audit results from: {input_path}")
    flagged = load_cleanup_words(input_path, args.confidence_threshold)
    print(f"  is_slang=false + confidence>={args.confidence_threshold}: {len(flagged)} words")

    words = build_word_set(flagged, extra_words)
    print(f"  + {len(extra_words)} manual extra words")
    print(f"  = {len(words)} unique words after dedup")

    print_plan(
        words=words,
        batch_size=args.batch_size,
        extra_words=extra_words,
        confidence_threshold=args.confidence_threshold,
        dry_run=args.dry_run,
        backup=args.backup,
        register_to_blacklist=not args.no_register_blacklist,
    )

    confirm_or_exit(skip_prompt=args.yes, dry_run=args.dry_run)

    asyncio.run(run_cleanup(
        words=words,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        backup=args.backup,
        register_to_blacklist=not args.no_register_blacklist,
    ))


if __name__ == "__main__":
    main()
