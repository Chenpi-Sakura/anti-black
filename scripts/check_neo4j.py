from neo4j import GraphDatabase

uri = 'bolt://192.168.148.128:7687'
driver = GraphDatabase.driver(uri, auth=('neo4j', 'neo4j123'))

with driver.session() as session:
    result = session.run('MATCH (n) RETURN labels(n)[0] as type, count(*) as count ORDER BY count DESC LIMIT 10')
    print('Neo4J nodes by type:')
    for record in result:
        print(f'  {record["type"]}: {record["count"]}')

    result = session.run('MATCH ()-[r]->() RETURN type(r) as type, count(*) as count ORDER BY count DESC LIMIT 10')
    print('\nNeo4J relationships by type:')
    for record in result:
        print(f'  {record["type"]}: {record["count"]}')

    result = session.run('MATCH (n) RETURN count(n) as node_count')
    node_count = result.single()["node_count"]
    result = session.run('MATCH ()-[r]->() RETURN count(r) as rel_count')
    rel_count = result.single()["rel_count"]
    print(f'\nTotal nodes: {node_count}, Total relationships: {rel_count}')

driver.close()