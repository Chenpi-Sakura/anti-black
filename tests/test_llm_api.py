#!/usr/bin/env python
"""Test MiniMax API connection."""
import os

os.environ['OPENAI_API_KEY'] = 'sk-cp-jnU2-zM8WX_D_UMrnmU4hhdVtj55gCTUd47nRSblVBVX_e0nE7R1Vmfa0yVXlAsG3edY4OJmYjaOFCYO4VTIxt1Y1nOUNEDU4Uw0LNoe5amzeDtZ1IpBr3o'
os.environ['LLM_API_BASE'] = 'https://api.minimaxi.com/v1'
os.environ['LLM_MODEL'] = 'MiniMax-M2.7'

from openai import OpenAI

client = OpenAI(
    base_url=os.environ['LLM_API_BASE'],
    api_key=os.environ['OPENAI_API_KEY']
)

print("Testing MiniMax API...")
response = client.chat.completions.create(
    model=os.environ['LLM_MODEL'],
    messages=[{'role': 'user', 'content': 'Say hello in one word'}]
)
print(f"Response: {response.choices[0].message.content}")
print(f"Model: {response.model}")
print("API test PASSED!")
