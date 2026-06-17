"""
Minimal YAML frontmatter parser for SKILL.md files.

We keep this as a ~30-line module rather than pulling in python-frontmatter
as a dependency.  Parses RFC 2822-style `---` delimiters.

Returns (frontmatter_dict: dict, body_str: str).
"""

import yaml
from typing import Any, Dict, Tuple


_ERR_BOTH = (
    "SKILL.md must have YAML frontmatter delimited by opening and closing "
    "`---` lines."
)
_ERR_NEITHER = (
    "SKILL.md must start with `---` on the first line."
)


def parse_skill_md(path: str) -> Tuple[Dict[str, Any], str]:
    """Read a SKILL.md file, parse its YAML frontmatter, return (meta, body).

    Raises ValueError on malformed frontmatter.
    """
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: {_ERR_NEITHER}")

    # Find closing `---` delimiter
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError(f"{path}: {_ERR_BOTH}")

    frontmatter_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1:]

    try:
        meta: Dict[str, Any] = yaml.safe_load("".join(frontmatter_lines))
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: YAML parse error: {e}")

    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter did not produce a dict")

    body = "".join(body_lines).strip()
    return meta, body
