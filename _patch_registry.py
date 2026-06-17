"""Add get_skill_references() to registry.py"""
import pathlib

path = pathlib.Path("agent/skills/registry.py")
content = path.read_text(encoding="utf-8")

func_def = """

def get_skill_references(name: str) -> Optional[str]:
    \"\"\"Load and concatenate reference files declared in a skill's reference_paths.

    Results are cached in _REF_CACHE (lazy-load on first call per skill).
    Paths are glob patterns relative to the skill's directory.
    Returns None if no reference_paths or no files matched.
    \"\"\"
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

    result = "\\n\\n".join(chunks)
    _REF_CACHE[name] = result
    return result


"""

content = content.replace("_SKILL_BODIES: Dict[str, str] = {}",
                           "_SKILL_BODIES: Dict[str, str] = {}\n\n# Cached reference file content (populated lazily on first request)\n_REF_CACHE: Dict[str, str] = {}")

content = content.replace("def list_all_skills() -> List[Skill]:",
                          func_def + "def list_all_skills() -> List[Skill]:")

path.write_text(content, encoding="utf-8")
print("Done")
