#!/usr/bin/env python
"""Smoke test for the CloudVLMClient (DashScope Qwen-VL).

Reads credentials from env (no hardcoded secrets):
  DASHSCOPE_API_KEY    - required
  DASHSCOPE_API_BASE   - default https://dashscope.aliyuncs.com/compatible-mode/v1
  DASHSCOPE_VLM_MODEL  - default qwen2.5-vl-32b

Run:
    export DASHSCOPE_API_KEY=<key>
    python tests/test_cloud_vlm.py
"""
import os
import sys

sys.path.insert(0, ".")

API_KEY = os.environ.get("DASHSCOPE_API_KEY")
API_BASE = os.environ.get(
    "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.environ.get("DASHSCOPE_VLM_MODEL", "qwen2.5-vl-32b")

if not API_KEY:
    print("ERROR: set DASHSCOPE_API_KEY env var first", file=sys.stderr)
    sys.exit(1)

from models import CloudVLMClient  # noqa: E402  (after env check)

client = CloudVLMClient(api_base=API_BASE, api_key=API_KEY, model=MODEL)

print(f"Model: {client.model}")
print(f"API Base: {client.api_base}")
print(f"Available: {client.is_available()}")
print("\nCloud VLM client initialized successfully!")
print("Note: Full image analysis requires an actual image file.")
