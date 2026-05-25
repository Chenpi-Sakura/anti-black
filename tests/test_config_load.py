#!/usr/bin/env python
"""Test config loading from .env file."""
import sys
sys.path.insert(0, '.')

from config import get_config, reload_config
reload_config('config.yaml')
c = get_config()

print('LLM api_base:', c.lightrag.llm.get('api_base'))
print('LLM model:', c.lightrag.llm.get('model'))
print('LLM api_key:', c.lightrag.llm.get('api_key')[:10] + '...')
print('Config loaded OK!')
