#!/usr/bin/env python
"""测试到各个数据库服务的连接"""
import sys

def test_mongodb():
    try:
        from pymongo import MongoClient
        client = MongoClient("192.168.148.128", 27017, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("MongoDB 连接成功")
        return True
    except Exception as e:
        print(f"MongoDB 连接失败: {e}")
        return False

def test_kafka():
    try:
        from kafka import KafkaProducer
        producer = KafkaProducer(
            bootstrap_servers=["192.168.148.128:9092"],
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000
        )
        producer.close(timeout=5)
        print("Kafka 连接成功")
        return True
    except Exception as e:
        print(f"Kafka 连接失败: {e}")
        return False

def test_neo4j():
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            "bolt://192.168.148.128:7687",
            auth=("neo4j", "neo4j123")
        )
        with driver.session() as session:
            result = session.run("RETURN 1 AS n")
            result.single()
        driver.close()
        print("Neo4j 连接成功")
        return True
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return False

def test_postgresql():
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="192.168.148.128",
            port=5432,
            user="antiblack",
            password="antiblack123",
            database="antiblack",
            connect_timeout=5
        )
        conn.close()
        print("PostgreSQL 连接成功")
        return True
    except Exception as e:
        print(f"PostgreSQL 连接失败: {e}")
        return False

def test_redis():
    try:
        import redis
        r = redis.Redis(host="192.168.148.128", port=6379, socket_timeout=5)
        r.ping()
        print("Redis 连接成功")
        return True
    except Exception as e:
        print(f"Redis 连接失败: {e}")
        return False

if __name__ == "__main__":
    print("===== 测试数据库连接 =====\n")
    results = [
        test_mongodb(),
        test_kafka(),
        test_neo4j(),
        test_postgresql(),
        test_redis()
    ]
    print()
    if all(results):
        print("所有连接测试通过!")
        sys.exit(0)
    else:
        print("部分连接测试失败")
        sys.exit(1)
