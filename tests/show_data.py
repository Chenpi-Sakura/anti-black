import asyncio
import asyncpg

async def show_data():
    pool = await asyncpg.create_pool(
        host='192.168.148.128',
        port=5432,
        user='antiblack',
        password='antiblack123',
        database='antiblack',
        timeout=5
    )
    async with pool.acquire() as conn:
        print("=" * 80)
        print("抖音视频数据 (douyin_aweme)")
        print("=" * 80)

        rows = await conn.fetch("""
            SELECT aweme_id, title, nickname, liked_count, comment_count, ip_location, source_keyword, create_time
            FROM douyin_aweme
            ORDER BY add_ts DESC
            LIMIT 20
        """)

        for r in rows:
            print(f"\nID: {r['aweme_id']}")
            print(f"  标题: {r['title'][:60] if r['title'] else '(无)'}...")
            print(f"  作者: {r['nickname']} | 点赞: {r['liked_count']} | 评论: {r['comment_count']}")
            print(f"  IP: {r['ip_location']} | 关键词: {r['source_keyword']}")

        print(f"\n共 {len(rows)} 条")

        print("\n" + "=" * 80)
        print("贴吧数据 (tieba_note)")
        print("=" * 80)

        tb_rows = await conn.fetch("""
            SELECT note_id, title, "desc", user_nickname, total_replay_num, ip_location, source_keyword
            FROM tieba_note
            ORDER BY add_ts DESC
            LIMIT 20
        """)

        if tb_rows:
            for r in tb_rows:
                print(f"\nID: {r['note_id']}")
                print(f"  标题: {r['title'][:60] if r['title'] else '(无)'}...")
                print(f"  作者: {r['user_nickname']} | 回复: {r['total_replay_num']}")
                print(f"  IP: {r['ip_location']} | 关键词: {r['source_keyword']}")
            print(f"\n共 {len(tb_rows)} 条")
        else:
            print("暂无数据")

        print("\n" + "=" * 80)
        print("评论数据")
        print("=" * 80)

        dy_cmt = await conn.fetchval("SELECT COUNT(*) FROM douyin_aweme_comment")
        tb_cmt = await conn.fetchval("SELECT COUNT(*) FROM tieba_comment")
        print(f"抖音评论: {dy_cmt} 条")
        print(f"贴吧评论: {tb_cmt} 条")

    await pool.close()

asyncio.run(show_data())