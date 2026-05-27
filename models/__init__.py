"""
Local models for AntiBlack system.
Handles embedding, classification, OCR, and VLM inference.
Also exports core data entities for MongoDB collections.
"""
from .embedding import EmbeddingModel
from .classifier import ClassificationModel
from .fasttext import FastTextModel
from .ocr import OCRModel
from .ollama_client import OllamaClient
from .cloud_vlm_client import CloudVLMClient
from .model_manager import ModelManager, get_model_manager, init_models
from .entities import (
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