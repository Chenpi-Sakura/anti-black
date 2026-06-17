"""
agent.skills — Skill bundle registry (YAML frontmatter + lazy body).

A Skill is a markdown file with YAML frontmatter (`SKILL.md`) that
encodes:
  - name / description / triggers   (for keyword-facilitated selection)
  - tools / plan_template           (for tool scoping and plan-then-execute)
  - body text                       (the "操作指南" — injected into system
                                     prompt when the skill is activated)

Skills are loaded once at startup (frontmatter parsed, body cached in mem).
Activation only happens if keywords + LLM confirm match; body is lazy-loaded
and only appended to the system prompt when the skill fires.
"""
