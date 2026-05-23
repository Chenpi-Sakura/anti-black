"""
Routes package for AntiBlack system.
"""
from .queries import queries_bp
from .clues import clues_bp
from .entities import entities_bp
from .feedback import feedback_bp
from .system import system_bp
from .taxonomy import taxonomy_bp
from .evolution import evolution_bp
from .export import export_bp
from .channels import channels_bp
from .metrics import metrics_bp
from .seed_words import seed_words_bp

__all__ = [
    'queries_bp',
    'clues_bp',
    'entities_bp',
    'feedback_bp',
    'system_bp',
    'taxonomy_bp',
    'evolution_bp',
    'export_bp',
    'channels_bp',
    'metrics_bp',
    'seed_words_bp'
]