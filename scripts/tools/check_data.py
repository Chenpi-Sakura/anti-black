import asyncpg
import asyncio

async def check():
    conn = await asyncpg.connect(
        host='192.168.148.128',
        port=5432,
        user='antiblack',
        password='antiblack123',
        database='antiblack'
    )
    await conn.execute('SET search_path = media_crawler')

    count = await conn.fetchval('SELECT COUNT(*) FROM douyin_aweme')
    print(f'Douyin videos: {count}')

    count = await conn.fetchval('SELECT COUNT(*) FROM douyin_aweme_comment')
    print(f'Douyin comments: {count}')

    count = await conn.fetchval('SELECT COUNT(*) FROM tieba_note')
    print(f'Tieba posts: {count}')

    await conn.close()

asyncio.run(check())