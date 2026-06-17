"""
Skill registry — load, match, and activate skills.

Design:
  - load_all_skills() is called once at module import time. It scans
    agent/skills/*/SKILL.md, parses the YAML frontmatter, and caches the
    Skill object + body string.
  - match_skill_by_keywords(query) does a loose substring match against
    skill.triggers and returns ≤3 candidates (sorted by hit density).
  - After the LLM confirm step (done in orchestrator.py), the caller calls
    get_skill_body(name) to lazy-load the markdown body for injection into
    the system prompt.

This module has NO dependency on services.orchestrator or agent.tools.
"""
from __future__ import annotations

import logging
import pathlib
from typing import Dict, List, Optional, Tuple

from agent.skills.base import Skill
from agent.skills.loader import parse_skill_md

logger = logging.getLogger(__name__)

# Global registries (populated once at module load)
_SKILLS: Dict[str, Skill] = {}
_SKILL_BODIES: Dict[str, str] = {}

# Cached reference file content (populated lazily on first request)
_REF_CACHE: Dict[str, str] = {}


def register_skill(skill: Skill, body: str) -> None:
    """Register a single skill (used by load_all_skills and tests)."""
    if skill.name in _SKILLS:
        logger.warning(f"Duplicate skill registration: {skill.name} (ignoring)")
        return
    _SKILLS[skill.name] = skill
    _SKILL_BODIES[skill.name] = body
    logger.debug(f"Registered skill: {skill.name}")


def load_all_skills(base: Optional[str] = None) -> None:
    """Scan agent/skills/*/SKILL.md, parse, and register.

    Safe to call multiple times (duplicates are silently skipped).
    Called automatically at the end of this module; explicit caller
    can re-scan after adding new skills at runtime.
    """
    search_root = pathlib.Path(base or pathlib.Path(__file__).parent)
    for skill_md in sorted(search_root.glob("*/SKILL.md")):
        try:
            meta, body = parse_skill_md(str(skill_md))
            skill = Skill(
                name=meta.get("name", skill_md.parent.name),
                description=meta.get("description", ""),
                skill_md_path=str(skill_md),
                tools=meta.get("tools", []),
                triggers=meta.get("triggers", []),
                plan_template=meta.get("plan_template", []),
                requires=meta.get("requires", []),
                reference_paths=meta.get("reference_paths", []),
                version=meta.get("version", "1.0"),
                enabled=meta.get("enabled", True),
            )
            register_skill(skill, body)
        except (ValueError, OSError) as e:
            logger.warning(f"Failed to load skill from {skill_md}: {e}")


def match_skill_by_keywords(query: str) -> List[Skill]:
    """Hybrid pre-filter: keyword substring match → ≤3 candidates.

    Scoring: count of triggers that appear in query_lower.
    Ties are broken by trigger count (more matches → higher priority).
    """
    q_lower = query.lower()
    scored: List[Tuple[int, Skill]] = []
    for skill in _SKILLS.values():
        if not skill.enabled:
            continue
        score = sum(1 for t in (skill.triggers or []) if t.lower() in q_lower)
        if score > 0:
            scored.append((score, skill))

    # Sort descending by score; stable so the load order breaks ties
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:3]]


def get_skill(name: str) -> Optional[Skill]:
    """Return the Skill object, or None if unknown."""
    return _SKILLS.get(name)


def get_skill_body(name: str) -> Optional[str]:
    """Return the cached markdown body for a skill (lazy-loaded at startup)."""
    return _SKILL_BODIES.get(name)




def get_skill_references(name: str) -> Optional[str]:
    """Load and concatenate reference files declared in a skill's reference_paths.

    Results are cached in _REF_CACHE (lazy-load on first call per skill).
    Paths are glob patterns relative to the skill's directory.
    Returns None if no reference_paths or no files matched.
    """
    if name in _REF_CACHE:
        return _REF_CACHE.get(name)

    skill = _SKILLS.get(name)
    if not skill or not skill.reference_paths:
        _REF_CACHE[name] = None
        return None

    skill_dir = pathlib.Path(skill.skill_md_path).parent
    chunks = []
    for pattern in skill.reference_paths:
        for fpath in sorted(skill_dir.glob(pattern)):
            try:
                text = fpath.read_text(encoding="utf-8")
                chunks.append(f"=== {fpath.name} ===")
                chunks.append(text)
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to read reference {fpath}: {e}")

    if not chunks:
        _REF_CACHE[name] = None
        return None

    result = "\n\n".join(chunks)
    _REF_CACHE[name] = result
    return result


def list_all_skills() -> List[Skill]:
    """Return all registered skills."""
    return list(_SKILLS.values())


# Auto-load at import time (safe: dedup by register_skill)
load_all_skills()
