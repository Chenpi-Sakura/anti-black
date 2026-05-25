#!/usr/bin/env python
"""Test Cloud VLM (DashScope Qwen-VL)."""
import sys
sys.path.insert(0, '.')

from models.cloud_vlm_client import CloudVLMClient

# Create client
client = CloudVLMClient(
    api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="sk-67027e263a3544a48632f25f5f17962a",
    model="qwen2.5-vl-32b"
)

print(f"Model: {client.model}")
print(f"API Base: {client.api_base}")
print(f"Available: {client.is_available()}")

# Create a simple test with a placeholder
# Note: We don't have an actual image to test, so just verify the client is initialized
print("\nCloud VLM client initialized successfully!")
print("Note: Full image analysis requires an actual image file.")
