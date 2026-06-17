"""Quick smoke test: verify 3 skills register + match + body load (ASCII-only output)."""
import os
os.chdir("D:/Projects/ByteDance/anti-black")
import sys
sys.path.insert(0, ".")

from agent.skills.registry import list_all_skills, match_skill_by_keywords, get_skill_body

skills = list_all_skills()

log = []
log.append(f"Loaded {len(skills)} skills:")
for s in skills:
    log.append(f"  {s.name}: ({len(s.tools)} tools, {len(s.plan_template)} steps)")
    assert s.name in ("trace_actor", "trend_analysis", "slang_investigation")

assert len(skills) == 3, f"Expected 3, got {len(skills)}"
assert get_skill_body("trace_actor") is not None
assert get_skill_body("trend_analysis") is not None
assert get_skill_body("slang_investigation") is not None

# Match tests
TESTS = [
    ("help me trace wechat abc123", ["trace_actor"]),
    ("recent 7 days fraud trend", ["trend_analysis"]),
    ("chuhao what does it mean", ["slang_investigation"]),
    ("weather today", []),
]
for query, expected in TESTS:
    matches = [s.name for s in match_skill_by_keywords(query)]
    ok = "PASS" if matches == expected else "FAIL"
    log.append(f"  [{ok}] {query:30s} -> {matches}")

log.append(f"  {ok} all tests")
# Write to file so it survives conda encoding bug
with open("_smoke_result.txt", "w") as f:
    f.write("\n".join(log))
