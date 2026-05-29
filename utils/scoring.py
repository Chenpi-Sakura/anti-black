def calculate_routing_score(
    risk_level: str,
    entity_count: int,
    slang_count: int,
    text_length: int,
    source_authority: str = "medium"
) -> float:
    """Calculate routing score for channel分流 decision."""
    # Base score from risk level
    risk_score = {
        'HIGH': 1.0,
        'MEDIUM': 0.5,
        'LOW': 0.2,
        'NORMAL': 0.0
    }.get(risk_level, 0.0)

    # Entity density (normalized to 0-0.3)
    entity_score = min(0.3, entity_count / 10)

    # Semantic complexity (based on slang density)
    if text_length > 0:
        slang_density = slang_count / (text_length / 100)
    else:
        slang_density = 0
    complexity_score = min(0.2, slang_density * 0.1)

    # Source authority
    authority_score = {
        'high': 0.15,
        'medium': 0.075,
        'low': 0.0
    }.get(source_authority, 0.075)

    return risk_score + entity_score + complexity_score + authority_score
