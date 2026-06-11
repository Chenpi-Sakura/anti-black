#!/usr/bin/env python
"""Smoke test for the primary LLM (default: MiniMax-M2.7 via OpenAI-compatible API).

Reads credentials from env (no hardcoded secrets):
  LLM_PRIMARY_API_KEY (or OPENAI_API_KEY as legacy fallback) - required
  LLM_PRIMARY_BASE_URL (or LLM_API_BASE)                   - default https://api.minimaxi.com/v1
  LLM_PRIMARY_MODEL (or LLM_MODEL)                         - default MiniMax-M2.7

Run:
    export LLM_PRIMARY_API_KEY=<key>
    python tests/test_llm_api.py
"""
import os
import sys

from openai import OpenAI

API_KEY = (
    os.environ.get("LLM_PRIMARY_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)
API_BASE = (
    os.environ.get("LLM_PRIMARY_BASE_URL")
    or os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
)
MODEL = (
    os.environ.get("LLM_PRIMARY_MODEL")
    or os.environ.get("LLM_MODEL", "MiniMax-M2.7")
)

if not API_KEY:
    print("ERROR: set LLM_PRIMARY_API_KEY (or OPENAI_API_KEY) env var first", file=sys.stderr)
    sys.exit(1)

client = OpenAI(base_url=API_BASE, api_key=API_KEY)

print(f"Testing {MODEL} via {API_BASE}...")
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": "Say hello in one word"}],
)
print(f"Response: {response.choices[0].message.content}")
print(f"Model: {response.model}")
print("API test PASSED!")
