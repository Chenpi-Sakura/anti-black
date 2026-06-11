"""
Audit slang_candidates (NEW/OBSERVED/LIKELY, occ>=10) to identify
daily-phrase stopwords polluting the LIKELY pool.

Asks LLM: is this a real black-market term or a generic daily phrase
that should be in the stopword set? Writes results to
scripts/audit_stopword_results.json.

Two-step flow: this script WRITES the JSON; apply_stopword_audit.py
READS it and mutates state (with operator --apply).
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import argparse
from datetime import datetime
from pathlib import Path

# === Output redirection (Windows GBK safe) - only set when running main() ===
_log_path = os.path.join(tempfile.gettempdir(), "audit_stopword_output.txt")
_log_file = None  # opened in main() so module import doesn't redirect stdout
_TEE_ACTIVE = False


class _TeeStream:
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


def _enable_tee() -> None:
    """Open log file and replace sys.stdout with a tee that mirrors to it.

    Called from main() so module imports don't trigger stdout redirection
    (which breaks test runners and other import-time logging).
    """
    global _log_file, _TEE_ACTIVE
    if _TEE_ACTIVE:
        return
    _log_file = open(_log_path, "w", encoding="utf-8", errors="replace")
    sys.stdout = _TeeStream(_log_file, sys.stdout)
    _TEE_ACTIVE = True


# === Project root ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
import psycopg2.extras
from openai import AsyncOpenAI

# === Config ===
DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "192.168.148.128"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": "antiblack",
    "password": "antiblack123",
    "database": "antiblack",
}

# Audit chain stays on qwen3.6-flash (Backlog-01 双盲设计 — audit LLM 与生产链
# 异构是有意的)。API key / base URL / model 全部 env 驱动，默认值兼容旧部署。
LLM_API_KEY = os.environ.get("AUDIT_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
LLM_API_BASE = os.environ.get(
    "AUDIT_LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.environ.get("AUDIT_LLM_MODEL", "qwen3.6-flash")

BATCH_SIZE = 10          # candidates per LLM call
CONTEXTS_PER_WORD = 3
MAX_CONCURRENCY = 8      # parallel LLM calls (matches .env LLM_MAX_CONCURRENT)
INTERVAL_SEC = 0.3       # pacing between calls (tighter than daemon's 1.0)
MAX_CANDIDATES = 6000    # SQL LIMIT
MIN_OCCURRENCE_COUNT = 10
OUTPUT_PATH = PROJECT_ROOT / "scripts" / "audit_stopword_results.json"


def load_candidates() -> list:
    """Load NEW/OBSERVED/LIKELY candidates with occurrence_count >= threshold."""
    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT candidate_word, status, occurrence_count, contexts
        FROM antiblack.slang_candidates
        WHERE status IN ('NEW', 'OBSERVED', 'LIKELY')
          AND occurrence_count >= %s
          AND (reject_until IS NULL OR reject_until < NOW())
        ORDER BY occurrence_count DESC
        LIMIT %s
    """, (MIN_OCCURRENCE_COUNT, MAX_CANDIDATES))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def extract_contexts(contexts_field, n=CONTEXTS_PER_WORD) -> list:
    """Extract n sample text strings from the contexts JSONB field.

    contexts is List[Tuple[message_id, text]] — keep text only.
    """
    if not contexts_field:
        return []
    out = []
    for item in contexts_field[:n]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append(str(item[1])[:100])
        elif isinstance(item, str):
            out.append(item[:100])
    return out


def build_prompt(batch: list) -> str:
    """Build the LLM prompt for a batch of candidates."""
    items_text = "\n".join(
        f"【{i+1}】候选词: {item['candidate_word']}\n"
        f"    出现次数: {item['occurrence_count']}\n"
        f"    当前状态: {item['status']}\n"
        f"    真实语料上下文:\n" +
        "\n".join(f"      {j+1}. {c[:80]}" for j, c in enumerate(extract_contexts(item.get('contexts'))))
        for i, item in enumerate(batch)
    )
    return f"""你是一个中文语料分析师。下面是 {len(batch)} 个被黑话学习流水线标记为"潜在黑话"的词汇。
但它们的出现次数已经较高(>={MIN_OCCURRENCE_COUNT}),疑似是日常通用短语而非黑灰产暗语。

请逐一判断每个词属于以下哪一类:

1. **stopword (is_stopword=true)**: 日常通用短语,任何语境下都不可能是黑话。
   例: "合适的话我就收了"、"我尝试"、"一直"、"努力"、"羡慕"、"买手机"、"合适就出"
   标准: 长度1-8字,无黑灰产语义负载,任何上下文都是日常表达。

2. **real_slang (is_stopword=false)**: 真实的黑灰产暗语/行话,只是因为使用频繁而待清理。
   例: "万粉号"、"出号"、"收号"、"换绑即可绝不找回"、"音符"、"专业服务"

3. **uncertain (is_stopword=null)**: 信息不足,需人工复核。

【关键判断维度】
- 词义是否涉及账号交易 / 刷量 / 跑分 / 杀猪盘 / 接码 / 私域引流 / 黑卡等
- 是否包含黑话特有的修辞(谐音/缩写/隐语)
- 上下文(若有)是否在描述黑灰产场景

{items_text}

请严格返回 JSON 数组(不要 markdown 标记),按编号顺序一一对应:
[
  {{"idx": 1, "word": "原词", "is_stopword": true/false/null, "confidence": 0-100, "reason": "一句话判断依据"}},
  ...
]"""


async def audit_batch(client: AsyncOpenAI, sem: asyncio.Semaphore, batch: list, idx_offset: int) -> list:
    """Send one batch to LLM, return list of result dicts (or empty on failure)."""
    async with sem:
        try:
            resp = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个中文语料分析师, 严格返回 JSON 数组。"},
                    {"role": "user", "content": build_prompt(batch)},
                ],
                max_tokens=4096,
                temperature=0.0,
                timeout=120,
            )
            text = resp.choices[0].message.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()
            results = json.loads(text)
            if not isinstance(results, list):
                return []
            # Validate + align with batch order
            aligned = []
            for i, r in enumerate(results):
                if not isinstance(r, dict):
                    continue
                word = batch[i]["candidate_word"]
                aligned.append({
                    "word": r.get("word", word),
                    "is_stopword": r.get("is_stopword"),
                    "confidence": r.get("confidence", 0),
                    "reason": r.get("reason", ""),
                })
            return aligned
        except Exception as e:
            print(f"  [batch error at offset {idx_offset}] {type(e).__name__}: {e}")
            return []


async def run_audit(candidates: list) -> list:
    """Batched audit. Returns merged list of {word, status, occ, llm_verdict, ...}."""
    if not LLM_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY not set in environment")

    client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE, timeout=120.0)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    # Build batches
    batches = [candidates[i:i+BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]
    print(f"Auditing {len(candidates)} candidates in {len(batches)} batches (concurrency={MAX_CONCURRENCY}, interval={INTERVAL_SEC}s)")

    tasks = []
    for idx, batch in enumerate(batches):
        tasks.append(audit_batch(client, sem, batch, idx * BATCH_SIZE))
        # Pacing: ensure at least INTERVAL_SEC between task launches
        await asyncio.sleep(INTERVAL_SEC / MAX_CONCURRENCY)

    started = time.time()
    batch_results = await asyncio.gather(*tasks)
    elapsed = time.time() - started
    print(f"All batches done in {elapsed:.1f}s ({len(candidates)/max(elapsed,1):.1f} candidates/s)")

    # Merge
    items = []
    for batch, results in zip(batches, batch_results):
        for i, r in enumerate(results):
            if i < len(batch):
                word_orig = batch[i]["candidate_word"]
                verdict = r.get("is_stopword")
                if verdict is True:
                    v = "stopword"
                elif verdict is False:
                    v = "real_slang"
                else:
                    v = "uncertain"
                items.append({
                    "word": word_orig,
                    "status": batch[i]["status"],
                    "occurrence_count": batch[i]["occurrence_count"],
                    "context_sample": extract_contexts(batch[i].get("contexts")),
                    "llm_verdict": v,
                    "confidence": r.get("confidence", 0),
                    "reason": r.get("reason", ""),
                })
    return items


def main():
    global MAX_CANDIDATES, MIN_OCCURRENCE_COUNT, OUTPUT_PATH
    _enable_tee()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--limit", type=int, default=MAX_CANDIDATES,
                        help=f"Max candidates to audit (default {MAX_CANDIDATES})")
    parser.add_argument("--min-occ", type=int, default=MIN_OCCURRENCE_COUNT,
                        help=f"Min occurrence_count (default {MIN_OCCURRENCE_COUNT})")
    args = parser.parse_args()

    MAX_CANDIDATES = args.limit
    MIN_OCCURRENCE_COUNT = args.min_occ
    OUTPUT_PATH = Path(args.output)

    print(f"=== Stopword Audit ===")
    print(f"  filter: status IN (NEW, OBSERVED, LIKELY) AND occurrence_count >= {MIN_OCCURRENCE_COUNT}")
    print(f"  limit: {MAX_CANDIDATES}")
    print(f"  model: {LLM_MODEL}")
    print(f"  output: {OUTPUT_PATH}")
    print()

    candidates = load_candidates()
    print(f"Loaded {len(candidates)} candidates")
    if not candidates:
        print("Nothing to audit")
        return

    items = asyncio.run(run_audit(candidates))

    # Summary
    by_verdict = {"stopword": 0, "real_slang": 0, "uncertain": 0}
    for it in items:
        by_verdict[it["llm_verdict"]] = by_verdict.get(it["llm_verdict"], 0) + 1
    high_conf_stopword = sum(1 for it in items
                             if it["llm_verdict"] == "stopword" and it["confidence"] >= 80)

    print()
    print(f"=== Audit Summary ===")
    print(f"  total audited:     {len(items)}")
    print(f"  is_stopword=true:  {by_verdict['stopword']}   <-- cleanup candidates")
    print(f"  is_stopword=false: {by_verdict['real_slang']}")
    print(f"  uncertain:         {by_verdict['uncertain']}")
    print(f"  high_conf(>=80) stopword: {high_conf_stopword}   <-- safe to auto-apply")
    print()
    print("Sample 20 stopwords to review:")
    samples = [it for it in items if it["llm_verdict"] == "stopword"][:20]
    for i, s in enumerate(samples, 1):
        print(f"  {i:>2}. {s['word']} (conf={s['confidence']}, {s['status']}, n={s['occurrence_count']})")
        if s['reason']:
            print(f"      reason: {s['reason'][:80]}")

    # Write JSON
    payload = {
        "audit_at": datetime.utcnow().isoformat() + "Z",
        "model": LLM_MODEL,
        "filter": {
            "statuses": ["NEW", "OBSERVED", "LIKELY"],
            "min_occurrence_count": MIN_OCCURRENCE_COUNT,
            "limit": MAX_CANDIDATES,
        },
        "total": len(items),
        "verdict_summary": {
            "stopword": by_verdict["stopword"],
            "real_slang": by_verdict["real_slang"],
            "uncertain": by_verdict["uncertain"],
            "high_conf_stopword": high_conf_stopword,
        },
        "items": items,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print()
    print(f"Results: {OUTPUT_PATH}")
    print(f"Log:     {_log_path}")


if __name__ == "__main__":
    main()
