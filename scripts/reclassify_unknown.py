#!/usr/bin/env python3
"""
Reclassify 7-day "未知/其他" clues with V3 rules + V3 LLM prompt.

Strategy:
1. Pull ~14K clues labeled 未知/其他 from last 7 days
2. Run V3 Stage 1 rules first (free, instant, ~25-35% coverage)
3. Run V3 LLM for the rest (with Few-Shot prompt + Semaphore(10) + exp backoff)
4. Bulk UPDATE in chunks of 500
5. Verify: 0 leftover 未知/其他 in processed set; if any, dump to JSONL for retry

V3 hardening:
- LLM client is a process-level singleton (no TIME_WAIT explosion)
- All chunks use the same LLM client + httpx.AsyncClient
- asyncio.gather with return_exceptions=True so one failure doesn't kill batch
- Rate-limit exhausts logs explicit "all retries exhausted" before returning None
- DB writes commit per chunk (no long tx)
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow running as a script from anywhere
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_config  # noqa: E402
from pipeline.classifier import Classifier  # noqa: E402
from services.database import PostgreSQLService  # noqa: E402
import logging  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('reclassify_unknown')

RECLASSIFY_DAYS = 7
RULE_CONFIDENCE_THRESHOLD = 0.7
LLM_SEMAPHORE = 10
LLM_RETRIES = [1, 2, 4, 8, 16]
CHUNK_SIZE = 500
LLM_CONFIDENCE_THRESHOLD = 0.5  # accept LLM only if confidence > this


def fetch_unknown_clue_ids(db, days=RECLASSIFY_DAYS, limit=20000) -> List[Dict[str, Any]]:
    """Pull clue_id + cleaned_text for 未知/其他 in last N days."""
    with db._get_cursor() as cur:
        cur.execute(
            """
            SELECT clue_id, cleaned_text, source_channel
            FROM antiblack.clues
            WHERE risk_label_level1 = '未知/其他'
              AND created_at > NOW() - INTERVAL '%s days'
              AND cleaned_text IS NOT NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (days, limit),
        )
        return cur.fetchall()


def try_rule(text: str, classifier: Classifier) -> Optional[Dict[str, str]]:
    """Try Stage 1 rule on a single text. Returns the rule hit or None."""
    result = classifier._classify_by_rules(text)
    if result is None:
        return None
    if result.confidence < RULE_CONFIDENCE_THRESHOLD:
        return None
    return {
        'level1': result.level1_label,
        'level2': result.level2_label,
        'source': 'rule',
    }


def build_prompt(text: str) -> str:
    """Build the V3 Few-Shot prompt (re-uses same template as classify.py)."""
    return f"""你是一个黑灰产情报分类专家。本系统聚焦【字节系黑灰产】（抖音/TikTok/头条/西瓜/飞书/豆包/剪映）。

分析以下文本，判断它属于哪种风险类型。优先看"行话暗号 + 交易特征"，不要因为字面直白就否定。

【风险类别与子类】：
1. 账号交易 - 账号买卖: 出号/换绑/租号; 代实名服务: 代实名/代过审
2. 流量作弊 - 刷粉/刷赞/刷量; 直播刷量: 直播刷人气/挂人气; 互刷涨粉/刷评论
3. 诈骗引流 - 刷单引流/杀猪盘/兼职诈骗; 私域引流: 私域+加粉/拉群; 灰产加盟: 招下线
4. 黑产工具 - 接码平台/群控工具/改机工具/IP池/猫池/矩阵号/自动化脚本
5. 灰产洗钱 - 跑分洗钱/四件套交易/代收代付/口令红包/洗钱通道
6. 未知/其他 - 情报有价值但模型无法分类
7. 无关 - 纯垃圾：聊天、广告、新闻、不相关游戏

【关键判断】：
- "未知/其他" = 情报有价值但分不出来（保留供人工 review）
- "无关" = 纯垃圾（应被过滤）
- 单字/双字高频日常词单独不构成风险判断
- 字面直白的高频交易词在黑产语境下是有效特征

【Few-Shot 示例】：
"出抖号" → 账号交易/账号买卖
"万粉号出" → 账号交易/账号买卖
"刷粉找小妹" → 流量作弊/刷粉
"直播刷人气找我" → 流量作弊/直播刷量
"跑分日结找我" → 灰产洗钱/跑分洗钱
"四件套出售" → 灰产洗钱/四件套交易
"IP池便宜" → 黑产工具/IP池/猫池
"矩阵号群控" → 黑产工具/矩阵号
"私域加粉拉群" → 诈骗引流/私域引流
"代实名找我" → 账号交易/代实名服务
"做自媒体 活跃账号" → 无关/噪声数据
"王者荣耀开黑" → 无关/不相关游戏/新闻
"今天天气真好" → 无关/噪声数据

文本: {text}

仅返回JSON格式的分类结果，不要包含其他内容：
{{"level1": "类别名", "level2": "子类别", "confidence": 0.0-1.0, "reason": "判断理由"}}"""


def parse_llm_response(raw: str) -> Optional[Dict[str, str]]:
    """Parse LLM JSON output, with multiple fallbacks."""
    import re
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text)
        text = text.strip('`').strip()
    # Find first { or [
    json_start = text.find('{')
    if json_start == -1:
        json_start = text.find('[')
    if json_start > 0:
        text = text[json_start:]
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    level1 = result.get('level1', '').strip()
    level2 = result.get('level2', '').strip()
    if level1 not in Classifier.LEVEL1_LABELS:
        return None
    return {
        'level1': level1,
        'level2': level2 or '未分类',
        'confidence': float(result.get('confidence', 0.0)),
    }


async def classify_one_with_retry(
    text: str,
    llm_client,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict[str, str]]:
    """Run one LLM classify with exponential backoff + explicit exhaustion log."""
    prompt = build_prompt(text)
    async with semaphore:
        total_attempts = len(LLM_RETRIES) + 1
        for attempt, delay in enumerate([0] + LLM_RETRIES):
            if delay:
                await asyncio.sleep(delay)
            try:
                raw = await llm_client.complete(prompt=prompt, max_tokens=512)
                parsed = parse_llm_response(raw)
                if parsed and parsed['confidence'] >= LLM_CONFIDENCE_THRESHOLD:
                    return {
                        'level1': parsed['level1'],
                        'level2': parsed['level2'],
                        'source': 'llm',
                    }
                return None
            except Exception as e:
                err_name = type(e).__name__
                if 'RateLimit' in err_name or 'Rate' in str(e):
                    if attempt == total_attempts - 1:
                        logger.error(
                            f"RateLimit exhausted after {total_attempts} retries: "
                            f"text={text[:20]!r}..."
                        )
                    continue
                logger.error(f"LLM fail (attempt {attempt}) {err_name}: {e}")
                return None
        # V3: explicit log when all retries exhausted
        logger.error(
            f"classify_one_with_retry all retries exhausted: text={text[:20]!r}..."
        )
        return None


async def main():
    config = get_config()
    db = PostgreSQLService.get_instance()
    classifier = Classifier(config)

    logger.info("Phase 3a: fetching 未知/其他 clues (last 7d)...")
    rows = fetch_unknown_clue_ids(db, RECLASSIFY_DAYS, limit=200)
    logger.info(f"Fetched {len(rows)} clues")
    if not rows:
        return

    clue_ids = [r['clue_id'] for r in rows]
    clue_texts = [r['cleaned_text'] for r in rows]

    # Phase 3b: Stage 1 rules first
    logger.info("Phase 3b: Stage 1 rule pass...")
    rule_updates = []
    llm_inputs = []  # (idx, text) where rule didn't match
    for idx, text in enumerate(clue_texts):
        hit = try_rule(text, classifier)
        if hit:
            rule_updates.append({
                'clue_id': clue_ids[idx],
                'risk_label_level1': hit['level1'],
                'risk_label_level2': hit['level2'],
                'classification_source': hit['source'],
                'classification_reason': 'V3 rule reclassify',
            })
        else:
            llm_inputs.append((idx, text))
    logger.info(f"Rule pass: {len(rule_updates)} matched, {len(llm_inputs)} to LLM")

    # Persist rule updates in chunks
    if rule_updates:
        logger.info(f"Persisting {len(rule_updates)} rule updates in chunks of {CHUNK_SIZE}...")
        await asyncio.to_thread(db.bulk_update_clue_labels, rule_updates, CHUNK_SIZE)

    # Phase 3c: LLM for the rest
    if not llm_inputs:
        logger.info("Nothing left for LLM, skipping.")
    else:
        logger.info("Phase 3c: LLM pass with V3 Few-Shot prompt + Semaphore + retries...")
        # V3: global LLM client singleton. Reads from env (LLM_PRIMARY_*)
        # already loaded by config's _load_env_file(). Don't pass config object.
        from models.clients.llm import LLMClient
        llm_client = LLMClient()

        semaphore = asyncio.Semaphore(LLM_SEMAPHORE)
        tasks = [
            classify_one_with_retry(text, llm_client, semaphore)
            for _, text in llm_inputs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        llm_updates = []
        llm_failures = 0
        for (idx, _), result in zip(llm_inputs, results):
            if isinstance(result, Exception):
                logger.error(f"LLM task exception: {result}")
                llm_failures += 1
                continue
            if result is None:
                llm_failures += 1
                continue
            llm_updates.append({
                'clue_id': clue_ids[idx],
                'risk_label_level1': result['level1'],
                'risk_label_level2': result['level2'],
                'classification_source': result['source'],
                'classification_reason': 'V3 LLM reclassify',
            })
        logger.info(
            f"LLM pass: {len(llm_updates)} updated, {llm_failures} failed/low-conf"
        )

        if llm_updates:
            logger.info(f"Persisting {len(llm_updates)} LLM updates in chunks...")
            await asyncio.to_thread(db.bulk_update_clue_labels, llm_updates, CHUNK_SIZE)

    # V3: verify completeness
    logger.info("Phase 3d: verifying completeness...")
    remaining = await asyncio.to_thread(
        db.count_clues_with_label, clue_ids, '未知/其他'
    )
    logger.info(f"Clues still labeled 未知/其他: {remaining}/{len(clue_ids)}")
    if remaining > 0:
        out_path = project_root / 'data' / 'reclassify_remaining.jsonl'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with db._get_cursor() as cur:
            cur.execute(
                """
                SELECT clue_id, cleaned_text
                FROM antiblack.clues
                WHERE risk_label_level1 = '未知/其他'
                  AND clue_id = ANY(%s)
                """,
                (clue_ids,),
            )
            leftover = cur.fetchall()
        with open(out_path, 'w', encoding='utf-8') as f:
            for r in leftover:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        logger.info(f"Wrote {len(leftover)} remaining clue_ids to {out_path}")


if __name__ == '__main__':
    asyncio.run(main())
