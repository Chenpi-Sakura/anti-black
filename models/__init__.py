"""
Local models for AntiBlack system.
Handles embedding, classification, OCR, and VLM inference.
"""
from .embedding import EmbeddingModel
from .classifier import ClassificationModel
from .fasttext import FastTextModel
from .ocr import OCRModel
from .ollama_client import OllamaClient
from .model_manager import ModelManager, get_model_manager, init_models

__all__ = [
    'EmbeddingModel',
    'ClassificationModel',
    'FastTextModel',
    'OCRModel',
    'OllamaClient',
    'ModelManager',
    'get_model_manager',
    'init_models',
]