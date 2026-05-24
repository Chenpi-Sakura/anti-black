"""
Embedding model using sentence-transformers (bge-small-zh).
"""
import os
import logging
from typing import List, Union, Optional

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Local embedding model for text vectorization."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        device: Optional[str] = None,
        normalize: bool = True
    ):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model name or local path
            device: 'cpu', 'cuda', 'mps' or None (auto)
            normalize: Whether to normalize embeddings
        """
        self.model_name = model_name
        self.normalize = normalize
        self._model = None
        self._device = device or self._auto_device()

    def _auto_device(self) -> str:
        """Auto-detect best device."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    def load(self):
        """Load model from disk/cache."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name} on {self._device}")
            self._model = SentenceTransformer(self.model_name, device=self._device)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
            logger.info("Falling back to mock embedding for demo mode")
            self._model = None

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32,
        show_progress: bool = False
    ) -> List[List[float]]:
        """
        Encode texts to embeddings.

        Args:
            texts: Single text or list of texts
            batch_size: Batch size for encoding
            show_progress: Show progress bar

        Returns:
            List of embedding vectors (each vector is list of floats)
        """
        if self._model is None:
            logger.warning("Embedding model not loaded, returning zero vectors")
            if isinstance(texts, str):
                return [[0.0] * 512]  # bge-small-zh uses 512 dim
            return [[0.0] * 512] * len(texts)

        self.load()

        if isinstance(texts, str):
            texts = [texts]

        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=show_progress,
            convert_to_numpy=True
        )

        return embeddings.tolist()

    def encode_query(self, query: str) -> List[float]:
        """Encode a single query (convenience method)."""
        return self.encode(query)[0]

    def similarity(self, text1: str, text2: str) -> float:
        """Calculate cosine similarity between two texts."""
        emb1 = self.encode(text1)[0]
        emb2 = self.encode(text2)[0]

        dot = sum(a * b for a, b in zip(emb1, emb2))
        norm1 = sum(a * a for a in emb1) ** 0.5
        norm2 = sum(b * b for b in emb2) ** 0.5

        return dot / (norm1 * norm2 + 1e-8)

    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        if self.model_name.startswith("BAAI/bge-small"):
            return 512
        elif "bge-base" in self.model_name:
            return 768
        elif "bge-large" in self.model_name:
            return 1024
        return 512  # default

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self):
        """Unload model from memory."""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Embedding model unloaded")