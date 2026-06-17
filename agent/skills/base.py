"""
Skill bundle dataclass.

Each Skill is defined by a SKILL.md file (YAML frontmatter + markdown body).
See agent/skills/trace_actor/SKILL.md for the canonical example.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Skill:
    """A re-usable analysis scenario bundle.

    Attributes:
        name:        Machine-readable identifier, e.g. "trace_actor".
        description: 1-2 sentence Chinese summary shown to the LLM via
                     system prompt. Must be concise and action-oriented.
        skill_md_path: Relative or absolute path to the SKILL.md file.
        tools:       Names of tools this skill exposes. Subset of the
                     full agent.tools registry.
        triggers:    Keyword / phrase list for pre-filter matching. Case-
                     insensitive substring match. Keep loose; the LLM
                     confirm step narrows.
        plan_template: Ordered list of plan-step labels (Chinese) shown
                     to the user as the "我的计划 (N 步)" stepper.
        requires:    List of other skill names that must be loaded first.
        version:     Semver string for cache busting.
        enabled:     False temporarily disables the skill without deleting
                     its SKILL.md.
    """
    name: str
    description: str
    skill_md_path: str
    tools: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    plan_template: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True
