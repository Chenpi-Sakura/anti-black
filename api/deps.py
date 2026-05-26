"""
Dependency injection for AntiBlack API
"""
from functools import lru_cache
from services.database import PostgreSQLService


@lru_cache
def get_db() -> PostgreSQLService:
    """Get database service singleton."""
    return PostgreSQLService.get_instance()