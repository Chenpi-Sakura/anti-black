"""查看 Slang Learning 当前状态"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from pipeline.slang_learning import SlangLearner
from config import get_config

config = get_config()
learner = SlangLearner(config)

# 读取之前的 pipeline 数据来训练
import asyncpg
import asyncio

async def process_recent_data():
    conn = await asyncpg.connect(
        host='192.168.148.128',
        port=5432,
        user='antiblack',
        password='antiblack123',
        database='antiblack'
    )
    await conn.execute('SET search_path = media_crawler')

    # 获取最近的抖音标题 (add_ts 是 unix timestamp bigint)
    rows = await conn.fetch('''
        SELECT title, "desc" FROM douyin_aweme
        ORDER BY add_ts DESC
        LIMIT 500
    ''')

    for row in rows:
        text = f"{row['title']} {row['desc']}"
        learner.process_text(text, source_channel='douyin')

    await conn.close()

async def main():
    print("Loading recent data from database...")
    await process_recent_data()

    stats = learner.get_candidate_stats()
    output = []
    output.append("=== Slang Learning Statistics ===")
    output.append(f"Total candidates: {sum(stats.values())}")
    output.append(f"Status breakdown: {stats}")

    output.append("\n=== LIKELY Status Candidates (need attention) ===")
    likely_candidates = [c for c in learner._candidates.values() if c.status == 'LIKELY']
    for c in likely_candidates:
        output.append(f"  - {c.word} (count: {c.occurrence_count})")

    output.append("\n=== OBSERVED Status Candidates ===")
    observed_candidates = [c for c in learner._candidates.values() if c.status == 'OBSERVED']
    for c in observed_candidates[:20]:
        output.append(f"  - {c.word} (count: {c.occurrence_count})")

    output.append("\n=== NEW Status Candidates (sample, first 30) ===")
    new_candidates = [c for c in learner._candidates.values() if c.status == 'NEW']
    for c in new_candidates[:30]:
        output.append(f"  - {c.word} (count: {c.occurrence_count})")

    result = '\n'.join(output)

    with open('slang_learning_status.txt', 'w', encoding='utf-8') as f:
        f.write(result)

    print(result)

asyncio.run(main())