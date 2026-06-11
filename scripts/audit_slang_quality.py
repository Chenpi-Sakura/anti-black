"""
Audit current CONFIRMED slangs in slang_mappings using LLM-as-judge.

Pulls all verified=True slang_raw from antiblack.slang_mappings, joins
5 contexts per word from slang_candidates.contexts (or clues fallback),
sends to qwen3.6-flash for is_slang / is_not_slang classification.

Output: scripts/audit_slang_results.json (per-word verdict + reason)
"""
import asyncio
import json
import os
import sys
import tempfile
import argparse
from datetime import datetime
from pathlib import Path

# === Output redirection for Windows GBK terminals ===
_log_path = os.path.join(tempfile.gettempdir(), "audit_slang_output.txt")
_log_file = open(_log_path, "w", encoding="utf-8", errors="replace")


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


sys.stdout = _TeeStream(_log_file, sys.stdout.__class__(open(os.devnull, "w")))

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
# 异构是有意的)。API key / base URL 改成 env 驱动，模型名也允许 env 覆盖
# 但默认值仍是 qwen3.6-flash。
LLM_API_KEY = os.environ.get("AUDIT_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
LLM_API_BASE = os.environ.get(
    "AUDIT_LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.environ.get("AUDIT_LLM_MODEL", "qwen3.6-flash")

BATCH_SIZE = 10  # slangs per LLM call
CONTEXTS_PER_WORD = 5
MAX_CONCURRENCY = 3  # parallel LLM calls


def load_all_verified_slangs():
    """Load all verified=True slang_raw + 5 contexts from slang_candidates.contexts."""
    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
    cur = conn.cursor()

    # Pull all CONFIRMED/STABLE candidates with their contexts
    cur.execute("""
        SELECT candidate_word, occurrence_count, status, contexts
        FROM antiblack.slang_candidates
        WHERE status IN ('CONFIRMED', 'STABLE')
        ORDER BY occurrence_count DESC
    """)
    rows = cur.fetchall()

    # Also pull all verified slang_mappings (in case some are NOT in candidates)
    cur.execute("""
        SELECT slang_raw, meaning
        FROM antiblack.slang_mappings
        WHERE verified = true
    """)
    mapping_rows = cur.fetchall()
    mapping_meanings = {r[0]: r[1] for r in mapping_rows}

    # Fallback: also pull from clues table for context
    cur.execute("""
        SELECT DISTINCT slang, raw_text
        FROM antiblack.clues c,
             jsonb_array_elements(c.slang_mappings) AS sm,
             jsonb_extract_path(sm, 'slang') AS slang
        WHERE jsonb_typeof(c.slang_mappings) = 'array'
              AND jsonb_array_length(c.slang_mappings) > 0
              AND raw_text IS NOT NULL
        LIMIT 5000
    """)
    clue_contexts_by_word = {}
    for slang, raw_text in cur.fetchall():
        clue_contexts_by_word.setdefault(slang, []).append(raw_text)
    print(f"Clue table provides fallback contexts for {len(clue_contexts_by_word)} words")

    conn.close()

    # Build per-word data
    items = []
    for cand_word, occ, status, contexts_jsonb in rows:
        # Parse contexts (JSONB array of strings)
        contexts = []
        if contexts_jsonb:
            try:
                parsed = contexts_jsonb if isinstance(contexts_jsonb, list) else json.loads(contexts_jsonb)
                contexts = [c for c in parsed if isinstance(c, str)]
            except (json.JSONDecodeError, TypeError):
                pass
        # Fallback to clue contexts
        if len(contexts) < CONTEXTS_PER_WORD and cand_word in clue_contexts_by_word:
            extra = clue_contexts_by_word[cand_word][:CONTEXTS_PER_WORD]
            contexts = (contexts + extra)[:CONTEXTS_PER_WORD]
        # Truncate to exactly 5
        contexts = contexts[:CONTEXTS_PER_WORD]
        items.append({
            "slang_raw": cand_word,
            "occ": occ,
            "status": status,
            "meaning_from_mappings": mapping_meanings.get(cand_word, ""),
            "contexts": contexts,
        })

    return items, mapping_meanings


def build_prompt(batch):
    """Build a single LLM prompt for a batch of slangs."""
    items_text = []
    for i, item in enumerate(batch, 1):
        ctx_lines = "\n".join(f"  {j+1}. {c[:120]}" for j, c in enumerate(item['contexts']))
        if not ctx_lines:
            ctx_lines = "  (no contexts available)"
        meaning = item.get('meaning_from_mappings', '') or "(no meaning recorded)"
        items_text.append(
            f"【{i}】候选词: {item['slang_raw']}\n"
            f"    系统记录的含义: {meaning}\n"
            f"    出现次数: {item['occ']}\n"
            f"    真实语料上下文:\n{ctx_lines}"
        )

    return f"""你是一个黑灰产情报分析师。下面是 {len(batch)} 个当前被系统标记为【已确认黑话 (CONFIRMED)】的词汇。
请逐一判断它们是否真的是黑灰产领域的暗语/行话/代称。

【判断标准】
- 是黑话 (is_slang=true): 涉及账号买卖 / 刷量 / 刷粉 / 跑分 / 杀猪盘 / 私域引流 /
  色情 / 赌博 / 黑卡 / 接码 / 群控 / 诈骗 / 黑产工具等任何黑灰产场景
- 不是黑话 (is_slang=false):
  - 通用词 / 日常用语 (如 "合作"、"投资"、"日常")
  - 内容标签 / 创作者 hashtag (如 "原创"、"笔记"、"搞笑")
  - 用户画像 / 群体描述 (如 "大学生"、"甜妹")
  - 商务 / 平台 / 行业词 (如 "平台"、"运营"、"报价")
  - 与黑灰产无任何关联的普通中文词

【关键提醒】
- 仅在语料中"频繁出现"不等于"是黑话"。"搞笑"在搞笑视频里出现 100 次也是普通词。
- 必须结合上下文是否与黑灰产场景相关来判断。
- 如果没有上下文可参考，且词义明显是日常词，直接判 false。

{chr(10).join(items_text)}

请严格返回 JSON 数组（不要 markdown 代码块标记），按上述编号顺序一一对应：
[
  {{"idx": 1, "slang_raw": "原词", "is_slang": true/false, "confidence": 0-100, "reason": "一句话解释"}},
  ...
]"""


async def audit_batch(client, batch, semaphore):
    """Send one batch to LLM, parse verdicts."""
    async with semaphore:
        prompt = build_prompt(batch)
        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.0,
                timeout=120,
            )
            content = response.choices[0].message.content.strip()
            # Strip any markdown code block markers
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content.rsplit("\n", 1)[0]
            verdicts = json.loads(content)
            return verdicts
        except json.JSONDecodeError as e:
            print(f"  [WARN] LLM returned non-JSON for batch of {len(batch)}: {e}")
            print(f"  Raw: {content[:300]}")
            return []
        except Exception as e:
            print(f"  [ERROR] LLM call failed: {e}")
            return []


async def run_audit(output_path: str, batch_size: int = BATCH_SIZE):
    print(f"Loading verified slangs from {DB_CONFIG['host']}...")
    items, mapping_meanings = load_all_verified_slangs()
    print(f"Total candidates to audit: {len(items)}")
    print(f"Items with at least 1 context: "
          f"{sum(1 for x in items if x['contexts'])}")
    print(f"Items with zero context: "
          f"{sum(1 for x in items if not x['contexts'])}")

    if not items:
        print("Nothing to audit.")
        return

    client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    # Build batches
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"Total batches: {len(batches)} (size={batch_size}, concurrency={MAX_CONCURRENCY})")

    tasks = [audit_batch(client, batch, semaphore) for batch in batches]
    results_per_batch = await asyncio.gather(*tasks)

    # Flatten
    verdicts = []
    for batch_verdicts in results_per_batch:
        verdicts.extend(batch_verdicts)

    # Index by slang_raw for lookup
    by_word = {v.get("slang_raw"): v for v in verdicts}

    # Merge with full items list
    merged = []
    for item in items:
        v = by_word.get(item["slang_raw"], {})
        merged.append({
            "slang_raw": item["slang_raw"],
            "occurrence_count": item["occ"],
            "status": item["status"],
            "meaning": item.get("meaning_from_mappings", ""),
            "context_count": len(item["contexts"]),
            "is_slang": v.get("is_slang"),
            "confidence": v.get("confidence"),
            "reason": v.get("reason"),
        })

    # Summary
    n_total = len(merged)
    n_yes = sum(1 for m in merged if m["is_slang"] is True)
    n_no = sum(1 for m in merged if m["is_slang"] is False)
    n_unknown = n_total - n_yes - n_no
    n_no_high_conf = sum(
        1 for m in merged
        if m["is_slang"] is False and (m.get("confidence") or 0) >= 80
    )

    output = {
        "audit_at": datetime.utcnow().isoformat() + "Z",
        "model": LLM_MODEL,
        "total": n_total,
        "is_slang_true": n_yes,
        "is_slang_false": n_no,
        "is_slang_unknown": n_unknown,
        "high_conf_false_for_cleanup": n_no_high_conf,
        "items": merged,
    }

    Path(output_path).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n=== Audit Summary ===")
    print(f"Total audited:     {n_total}")
    print(f"  is_slang=true:   {n_yes}")
    print(f"  is_slang=false:  {n_no}")
    print(f"  unknown:         {n_unknown}")
    print(f"  high_conf(>=80) false: {n_no_high_conf}  <-- cleanup candidates")
    print(f"\nResults written to: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=str(PROJECT_ROOT / "scripts" / "audit_slang_results.json"),
        help="Output JSON path",
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    if not LLM_API_KEY:
        print("ERROR: DASHSCOPE_API_KEY env var not set")
        sys.exit(1)

    asyncio.run(run_audit(args.output, args.batch_size))


if __name__ == "__main__":
    main()
