#!/usr/bin/env python
"""Smoke test for the DashScope Qwen fallback.

Reads credentials from env (no hardcoded secrets):
  DASHSCOPE_API_KEY  - required
  DASHSCOPE_API_BASE - default https://dashscope.aliyuncs.com/compatible-mode/v1
  DASHSCOPE_MODEL    - default qwen3.6-flash

Run:
    export DASHSCOPE_API_KEY=<key>
    python tests/test_dashscope.py
"""
import os
import sys

from openai import OpenAI

API_KEY = os.environ.get("DASHSCOPE_API_KEY")
API_BASE = os.environ.get(
    "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.environ.get("DASHSCOPE_MODEL", "qwen3.6-flash")

if not API_KEY:
    print("ERROR: set DASHSCOPE_API_KEY env var first", file=sys.stderr)
    sys.exit(1)

client = OpenAI(base_url=API_BASE, api_key=API_KEY)

print(f"Testing {MODEL} via {API_BASE}...")
messages = [{"role": "user", "content": "你是谁?用一句话回答"}]
completion = client.chat.completions.create(
    model=MODEL,
    messages=messages,
    extra_body={"enable_thinking": False},
)
print(f"Response: {completion.choices[0].message.content}")
print("API test PASSED!")
