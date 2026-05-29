"""
Local models for AntiBlack system.
Handles embedding, classification, OCR, and VLM inference.
Also exports core data entities for database collections.
"""
from .ml.embedding import EmbeddingModel
from .ml.classifier import ClassificationModel
from .ml.fasttext import FastTextModel
from .ml.ocr import OCRModel
from .clients.ollama import OllamaClient
from .clients.cloud_vlm import CloudVLMClient
from .ml.model_manager import ModelManager, get_model_manager, init_models
from .domain.entities import (
    Entity, MessageRef, SlangMapping, SlangCandidate, QueryTask, Clue,
    Feedback, SeedWord, Proposal, ExportTask, Channel, Metrics, AutoEvolution,
    Conversation,
    EntityType, RiskLevel, SourceChannel, ClassificationSource, QueryStatus,
    ExportStatus, PatrolStatus, SystemStatus, SlangStatus, SeedWordStatus, RetrainStatus
)

__all__ = [
    # ML models
    'EmbeddingModel',
    'ClassificationModel',
    'FastTextModel',
    'OCRModel',
    'OllamaClient',
    'CloudVLMClient',
    'ModelManager',
    'get_model_manager',
    'init_models',
    # Data entities
    'Entity',
    'MessageRef',
    'SlangMapping',
    'SlangCandidate',
    'QueryTask',
    'Clue',
    'Feedback',
    'SeedWord',
    'Proposal',
    'ExportTask',
    'Channel',
    'Metrics',
    'AutoEvolution',
    'Conversation',
    'EntityType',
    'RiskLevel',
    'SourceChannel',
    'ClassificationSource',
    'QueryStatus',
    'ExportStatus',
    'PatrolStatus',
    'SystemStatus',
    'SlangStatus',
    'SeedWordStatus',
    'RetrainStatus',
]