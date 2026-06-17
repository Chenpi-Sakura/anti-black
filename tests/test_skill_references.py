"""Minimal smoke test for PR2 new code: reference_paths injection."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.skills.registry import list_all_skills, get_skill_references

# 1) Verify break-risk-intel loaded with reference_paths
skills = list_all_skills()
target = None
for s in skills:
    if s.name == "break-risk-intel":
        target = s
        break
assert target is not None, "break-risk-intel not loaded"
assert len(target.reference_paths) == 4, f"Expected 4 patterns, got {target.reference_paths}"

# 2) get_skill_references loads and caches
refs = get_skill_references("break-risk-intel")
assert refs is not None, "references returned None"
assert len(refs) > 1000, f"too short: {len(refs)}"
assert "=== risk-index.md ===" in refs, "missing risk-index.md header"
assert "=== account-risk.md ===" in refs, "missing knowledge header"
assert "R0000" in refs, "missing BREAK risk ID reference"

# 3) Other skills return None (no reference_paths)
for n in ["trace-actor", "trend-analysis", "slang-investigation"]:
    assert get_skill_references(n) is None, f"{n} should have no refs"

print("ALL PASSED")
