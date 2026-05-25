#!/usr/bin/env python
"""Test DashScope API with Qwen3.6."""
import os
os.environ['DASHSCOPE_API_KEY'] = 'sk-67027e263a3544a48632f25f5f17962a'
os.environ['LLM_API_BASE'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
os.environ['LLM_MODEL'] = 'qwen3.6-27b'

from openai import OpenAI

client = OpenAI(
    api_key=os.environ['DASHSCOPE_API_KEY'],
    base_url=os.environ['LLM_API_BASE']
)

print("Testing DashScope API with Qwen3.6-27b...")
messages = [{"role": "user", "content": "你是谁?用一句话回答"}]

completion = client.chat.completions.create(
    model=os.environ['LLM_MODEL'],
    messages=messages,
    extra_body={"enable_thinking": False}
)

print(f"Response: {completion.choices[0].message.content}")
print("API test PASSED!")
