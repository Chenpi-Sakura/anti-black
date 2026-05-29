"""Debug router scoring - output to file"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from pipeline.router import Router, RISK_LABEL_TO_SCORE

router = Router()

# Test message with 账号交易 (HIGH risk)
test_msg = {
    "message_id": "test_001",
    "source_channel": "douyin",
    "risk_level": "账号交易",  # Should map to HIGH
    "entities": [],
    "slang_mappings": [],
    "raw_text": "test text",
    "cleaned_text": "test text",
}

score = router._calculate_score(test_msg)

output = []
output.append(f"Score: {score}")
output.append(f"Threshold: {router.default_threshold}")
output.append(f"Would route to: {'deep' if score >= router.default_threshold else 'light'}")
output.append(f"Mapping for '账号交易': {RISK_LABEL_TO_SCORE.get('账号交易', 'NOT FOUND')}")

# Score components
output.append("\nScore breakdown:")
output.append(f"  risk_level = 0.3 * 1.0 = {0.3 * 1.0}")
output.append(f"  entity_density = 0.2 * 0 = 0")
output.append(f"  semantic_complexity = 0.2 * 0 = 0")
output.append(f"  novelty = 0.15 * 0.15 = {0.15 * 0.15}")
output.append(f"  source_authority = 0.15 * 0.05 * 3 = {0.15 * 0.05 * 3}")
output.append(f"  Total: {0.3 + 0 + 0 + 0.0225 + 0.0225}")

with open('router_debug.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))