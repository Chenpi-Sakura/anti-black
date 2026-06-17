"""Quick smoke test: verify 3 skills register + match + body load."""
from agent.skills.registry import list_all_skills, match_skill_by_keywords, get_skill_body

skills = list_all_skills()
print(f"Loaded {len(skills)} skills:")
for s in skills:
    print(f"  {s.name}: {s.description[:30]}... ({len(s.tools)} tools, {len(s.plan_template)} steps)")

assert len(skills) == 3, f"Expected 3 skills, got {len(skills)}"
assert get_skill_body("trace_actor") is not None
assert get_skill_body("trend_analysis") is not None
assert get_skill_body("slang_investigation") is not None

# Match tests
for query, expected in [
    ("帮我溯源微信号 abc123", ["trace_actor"]),
    ("近7天诈骗类有什么趋势", ["trend_analysis"]),
    ("chuhao 是啥意思", ["slang_investigation"]),
    ("今天天气", []),
]:
    matches = [s.name for s in match_skill_by_keywords(query)]
    assert matches == expected, f"query={query!r}: expected {expected}, got {matches}"
    print(f"  Match {query!r:30s} -> {matches}")

print("\nAll smoke tests PASSED")
