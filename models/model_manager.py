"""
Model manager - unified interface for all local models.
Provides lazy loading and singleton pattern for model instances.
"""
import os
import logging
from typing import Optional, List, Dict, Any
from functools import lru_cache

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Unified model manager for all local models.
    Supports: Embedding, Classification, FastText, OCR, Ollama.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._embedding_model = None
        self._classification_model = None
        self._fasttext_model = None
        self._ocr_model = None
        self._ollama_client = None
        self._cloud_vlm_client = None
        self._config = None
        self._initialized = True
        logger.info("ModelManager initialized")

    def init_from_config(self, config: Dict[str, Any]):
        """Initialize models from config dict."""
        self._config = config

        # Initialize Cloud VLM client (优先使用云端VLM)
        cloud_vlm_cfg = config.get('cloud_vlm', {})
        if cloud_vlm_cfg.get('enabled', False):
            from .cloud_vlm_client import CloudVLMClient
            self._cloud_vlm_client = CloudVLMClient(
                api_base=cloud_vlm_cfg.get('api_base', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                api_key=cloud_vlm_cfg.get('api_key'),
                model=cloud_vlm_cfg.get('model', 'qwen2.5-vl-32b'),
                timeout=cloud_vlm_cfg.get('timeout', 120)
            )
            logger.info("Cloud VLM client initialized")

        # Initialize Ollama client (VLM和Embedding备选)
        ollama_cfg = config.get('ollama', {})
        if ollama_cfg.get('enabled', False):
            from .ollama_client import OllamaClient
            self._ollama_client = OllamaClient(
                base_url=ollama_cfg.get('base_url', 'http://localhost:11434'),
                vlm_model=ollama_cfg.get('vlm_model', 'qwen2-vl:2b'),
                llm_model=ollama_cfg.get('llm_model', 'qwen2.5:7b'),
                timeout=ollama_cfg.get('timeout', 120)
            )
            logger.info("Ollama client initialized")

    @property
    def embedding(self):
        """Get or create embedding model."""
        if self._embedding_model is None:
            from .embedding import EmbeddingModel

            config = self._config.get('local_models', {}).get('embedding', {}) if self._config else {}
            self._embedding_model = EmbeddingModel(
                model_name=config.get('model_name', 'BAAI/bge-small-zh-v1.5'),
                device=config.get('device', 'auto'),
                normalize=config.get('normalize', True)
            )
            logger.info("Embedding model created (lazy loading)")
        return self._embedding_model

    @property
    def classifier(self):
        """Get or create classification model."""
        if self._classification_model is None:
            from .classifier import ClassificationModel

            config = self._config.get('local_models', {}).get('classifier', {}) if self._config else {}
            self._classification_model = ClassificationModel(
                model_type=config.get('model_type', 'xgboost'),
                model_path=config.get('model_path'),
                label_encoder_path=config.get('label_encoder_path')
            )
            logger.info("Classification model created (lazy loading)")
        return self._classification_model

    @property
    def fasttext(self):
        """Get or create FastText model."""
        if self._fasttext_model is None:
            from .fasttext import FastTextModel

            config = self._config.get('local_models', {}).get('fasttext', {}) if self._config else {}
            self._fasttext_model = FastTextModel(
                model_path=config.get('model_path'),
                lid_code="lid.176.bin"
            )
            logger.info("FastText model created (lazy loading)")
        return self._fasttext_model

    @property
    def ocr(self):
        """Get or create OCR model."""
        if self._ocr_model is None:
            from .ocr import OCRModel

            config = self._config.get('local_models', {}).get('ocr', {}) if self._config else {}
            self._ocr_model = OCRModel(
                use_angle_cls=config.get('use_angle_cls', True),
                lang=config.get('lang', 'ch'),
                device=config.get('device', 'cpu')
            )
            logger.info("OCR model created (lazy loading)")
        return self._ocr_model

    @property
    def ollama(self):
        """Get or create Ollama client."""
        if self._ollama_client is None:
            from .ollama_client import OllamaClient
            self._ollama_client = OllamaClient()
            logger.info("Ollama client created (lazy loading)")
        return self._ollama_client

    @property
    def cloud_vlm(self):
        """Get or create Cloud VLM client."""
        if self._cloud_vlm_client is None:
            from .cloud_vlm_client import CloudVLMClient
            self._cloud_vlm_client = CloudVLMClient()
            logger.info("Cloud VLM client created (lazy loading)")
        return self._cloud_vlm_client

    def get_vlm_client(self):
        """Get the best available VLM client (cloud优先)."""
        if self._cloud_vlm_client is not None:
            return self._cloud_vlm_client
        if self._ollama_client is not None:
            return self._ollama_client
        return None

    def load_all(self):
        """Pre-load all models."""
        logger.info("Loading all models...")
        self.embedding.load()
        self.classifier.load()
        self.fasttext.load()
        self.ocr.load()
        logger.info("All models loaded")

    def unload_all(self):
        """Unload all models from memory."""
        logger.info("Unloading all models...")
        if self._embedding_model:
            self._embedding_model.unload()
        if self._ocr_model:
            self._ocr_model.unload()
        logger.info("All models unloaded")

    def get_status(self) -> Dict[str, bool]:
        """Get loading status of all models."""
        return {
            'embedding': self._embedding_model is not None,
            'classifier': self._classification_model is not None,
            'fasttext': self._fasttext_model is not None,
            'ocr': self._ocr_model is not None,
            'ollama': self._ollama_client is not None,
            'cloud_vlm': self._cloud_vlm_client is not None,
        }


# Global model manager instance
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get or create global model manager."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager


def init_models(config: Dict[str, Any]):
    """Initialize model manager from config."""
    manager = get_model_manager()
    manager.init_from_config(config)
    return manager