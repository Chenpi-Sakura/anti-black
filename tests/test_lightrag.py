#!/usr/bin/env python
"""Test LightRAG connectivity and basic operations."""
import sys
import os

# Fix encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Add LightRAG local clone to path
LIGHT_RAG_PATH = os.path.join(PROJECT_ROOT, 'LightRAG')
sys.path.insert(0, LIGHT_RAG_PATH)

# Load .env first
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

# Export LightRAG env vars if not already set
os.environ.setdefault('NEO4J_USERNAME', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'neo4j123')
os.environ.setdefault('POSTGRES_USER', 'antiblack')
os.environ.setdefault('POSTGRES_PASSWORD', 'antiblack123')
os.environ.setdefault('POSTGRES_DATABASE', 'antiblack')
os.environ.setdefault('POSTGRES_HOST', '192.168.148.128')
os.environ.setdefault('POSTGRES_PORT', '5432')
# Ollama
os.environ.setdefault('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
os.environ.setdefault('OLLAMA_API_KEY', 'ollama')
os.environ.setdefault('OLLAMA_EMBEDDING_MODEL', 'bge-m3:latest')

from config import get_config

def test_lightrag():
    """Test LightRAG with remote storage."""
    print("=" * 60)
    print("LightRAG Connectivity Test")
    print("=" * 60)

    config = get_config()
    lightrag_cfg = config.lightrag

    print("\n[1] Configuration:")
    print(f"    Working dir: {lightrag_cfg.working_dir}")
    print(f"    LLM model: {lightrag_cfg.llm.get('model', 'N/A')}")
    print(f"    Embedding: {lightrag_cfg.embedding.get('model', 'N/A')}")
    print(f"    Storage:")
    print(f"      - Graph: {lightrag_cfg.storage.get('graph', 'N/A')}")
    print(f"      - Vector: {lightrag_cfg.storage.get('vector', 'N/A')}")
    print(f"      - KV: {lightrag_cfg.storage.get('kv', 'N/A')}")
    print(f"    Neo4j: {lightrag_cfg.neo4j.get('uri', 'N/A')}")
    print(f"    PostgreSQL: {lightrag_cfg.postgresql.get('host', 'N/A')}:{lightrag_cfg.postgresql.get('port', 'N/A')}")

    print("\n[2] Environment variables check:")
    print(f"    NEO4J_USERNAME: {os.environ.get('NEO4J_USERNAME', 'NOT SET')}")
    print(f"    NEO4J_PASSWORD: {'*' * len(os.environ.get('NEO4J_PASSWORD', ''))}")
    print(f"    POSTGRES_USER: {os.environ.get('POSTGRES_USER', 'NOT SET')}")
    print(f"    POSTGRES_PASSWORD: {'*' * len(os.environ.get('POSTGRES_PASSWORD', ''))}")
    print(f"    POSTGRES_HOST: {os.environ.get('POSTGRES_HOST', 'NOT SET')}")
    print(f"    POSTGRES_PORT: {os.environ.get('POSTGRES_PORT', 'NOT SET')}")

    print("\n[3] Testing LightRAG initialization...")
    try:
        # Direct import to avoid services/__init__.py which requires pymongo
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lightrag_service",
            os.path.join(PROJECT_ROOT, "services", "lightrag_service.py")
        )
        lightrag_service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lightrag_service)
        LightRAGIntegrator = lightrag_service.LightRAGIntegrator
        import asyncio

        integrator = LightRAGIntegrator(config._config)

        async def init_test():
            await integrator.initialize()
            return integrator._initialized

        initialized = asyncio.run(init_test())
        if initialized:
            print("    [OK] LightRAG initialized successfully!")
        else:
            print("    [FAIL] LightRAG initialization returned False")
            return False

        print("\n[4] Testing text insertion...")
        async def insert_test():
            test_text = "出抖号，千粉，换绑稳，加V:dyhao668 [风险类型: 账号交易 / 抖音号买卖]"
            result = await integrator.insert(test_text, {"source": "test"})
            return result

        insert_result = asyncio.run(insert_test())
        if insert_result:
            print("    [OK] Text insertion successful!")
        else:
            print("    [FAIL] Text insertion failed")
            return False

        print("\n[5] Testing query...")
        async def query_test():
            result = await integrator.query("抖音号买卖 出号", mode="hybrid", top_k=5)
            return result

        query_result = asyncio.run(query_test())
        if query_result and "results" in query_result:
            print(f"    [OK] Query successful! Got {len(query_result.get('results', []))} results")
        else:
            print("    [FAIL] Query failed or returned no results")

        print("\n[6] Testing finalize...")
        async def finalize_test():
            await integrator.finalize()

        asyncio.run(finalize_test())
        print("    [OK] Finalize successful!")

        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n    [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_lightrag()
    sys.exit(0 if success else 1)