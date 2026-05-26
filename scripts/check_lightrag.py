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
    await conn.execute('SET search_path = public')

    # Check LightRAG tables for data
    tables = [
        'lightrag_doc_chunks',
        'lightrag_doc_full',
        'lightrag_doc_status',
        'lightrag_entity_chunks',
        'lightrag_full_entities',
        'lightrag_full_relations',
        'lightrag_vdb_chunks',
        'lightrag_vdb_entity',
        'lightrag_vdb_relation',
    ]

    print("LightRAG table counts:")
    for table in tables:
        try:
            count = await conn.fetchval(f'SELECT COUNT(*) FROM {table}')
            print(f'  {table}: {count} rows')
        except Exception as e:
            print(f'  {table}: error - {e}')

    await conn.close()

asyncio.run(check())