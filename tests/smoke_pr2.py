"""PR2 smoke test: skill registry + matching + references."""
import sys, os
os.chdir("D:/Projects/ByteDance/anti-black")
sys.path.insert(0, ".")

from agent.skills.registry import list_all_skills, match_skill_by_keywords, get_skill_body, get_skill_references, _REF_CACHE

# 1) Skills loaded
skills = list_all_skills()
assert len(skills) == 4, f"Expected 4, got {len(skills)}"
names = [s.name for s in skills]
assert "trace-actor" in names
assert "trend-analysis" in names
assert "slang-investigation" in names
assert "break-risk-intel" in names

# Confirm reference_paths
for s in skills:
    if s.name == "break-risk-intel":
        assert s.reference_paths == ["references/*.md", "knowledge/*.md", "examples/*.md", "templates/*.md"], f"Got {s.reference_paths}"
        print(f"  [PASS] break-risk-intel has reference_paths: {s.reference_paths}")
    else:
        assert s.reference_paths == [], f"{s.name} should have empty refs, got {s.reference_paths}"

# 2) Keyword matching
for query, expected in [
    ("trace wechat abc", ["trace-actor"]),  # no 'help'
    ("recent 7 days trend", ["trend-analysis"]),
    ("chuhao what does it mean", ["slang-investigation"]),
    ("fraud case analysis", ["break-risk-intel"]),
    ("weather today", []),
]:
    matches = [s.name for s in match_skill_by_keywords(query)]
    ok = "PASS" if matches == expected else "FAIL"
    print(f"  [{ok}] match({query!r:30s}) -> {matches}")
    assert matches == expected, f"Expected {expected}, got {matches}"

# 3) body
assert get_skill_body("break-risk-intel") is not None
assert get_skill_body("trace-actor") is not None
print("  [PASS] bodies loaded")

# 4) references
refs = get_skill_references("break-risk-intel")
assert refs is not None, "break-risk-intel should have references"
assert len(refs) > 1000, f"refs too short: {len(refs)}"
assert "=== risk-index.md ===" in refs, "Should contain risk-index.md header"
assert "=== account-risk.md ===" in refs, "Should contain knowledge"
assert "R0000" in refs, "Should contain BREAK risk IDs"
print(f"  [PASS] refs: {len(refs)} chars, contains risk-index, account-risk, R0000")

# 5) no refs for other skills
assert get_skill_references("trace-actor") is None
assert get_skill_references("trend-analysis") is None
assert get_skill_references("slang-investigation") is None
print("  [PASS] other skills have no references (expected)")

# 6) cache hit
assert "break-risk-intel" in _REF_CACHE
assert "trace-actor" in _REF_CACHE
print("  [PASS] cache populated")

print("\nALL SMOKE TESTS PASSED")
