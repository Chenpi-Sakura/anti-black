"""Quick LLM provider health check. Pings each provider and reports health."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.clients.llm import LLMClient, AllProvidersExhausted
from utils.logger import configure_root_logger
import logging

configure_root_logger(log_level=logging.WARNING)
log = logging.getLogger("llm_health")


async def main():
    print('=' * 70)
    print('  LLM Provider Health')
    print('=' * 70)
    try:
        client = LLMClient()
    except ValueError as e:
        print(f'[FATAL] {e}')
        return

    health = client.get_health()
    for p in health['providers']:
        status = 'OK'
        if p['circuit_open_seconds_remaining'] > 0:
            status = f'CIRCUIT OPEN ({p["circuit_open_seconds_remaining"]}s)'
        elif p['consecutive_failures'] > 0:
            status = f'WARN (failures={p["consecutive_failures"]})'
        print(f'  [{status:<24}] {p["name"]:<12} model={p["model"]:<40}')

    print()
    print('=== PING each provider ===')
    for provider in client.providers:
        if client._is_circuit_open(provider):
            print(f'  [SKIP] {provider["name"]:<12} (circuit open)')
            continue
        try:
            content = await client.complete('ping', system_prompt='Reply with one word: pong')
            print(f'  [OK]   {provider["name"]:<12} -> {content[:60]!r}')
            client._record_success(provider)
        except AllProvidersExhausted:
            print(f'  [FAIL] {provider["name"]:<12} (all providers exhausted)')
        except Exception as e:
            err_type = type(e).__name__
            err_msg = str(e)[:80]
            print(f'  [FAIL] {provider["name"]:<12} {err_type}: {err_msg}')

    print()
    print('=== Updated health ===')
    for p in client.get_health()['providers']:
        print(f'  {p["name"]:<12} failures={p["consecutive_failures"]:<3} circuit_open={p["circuit_open_seconds_remaining"]}s')


asyncio.run(main())
