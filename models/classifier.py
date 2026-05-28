"""
Classification model using XGBoost or sklearn linear classifier.
"""
import os
import pickle
import logging
import threading
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class ClassifierModel:
    """
    Local classification model with atomic hot-swap support.
    FR-EVO-03: Hot swap mechanism

    Design: Lock-free inference, lock only for pointer swap.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._model: 'LogisticRegression' = None
        self._label_encoder: 'LabelEncoder' = None
        self._version: str = None

    @classmethod
    def get_instance(cls) -> 'ClassifierModel':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def load(self, model_path: str):
        """Load model from joblib checkpoint."""
        import joblib
        checkpoint = joblib.load(model_path)
        self._model = checkpoint['model']
        self._label_encoder = checkpoint['label_encoder']
        self._version = checkpoint['version']

    def hot_swap(self, new_model_path: str) -> bool:
        """
        Atomic hot swap: load new model then atomically switch pointers.
        During swap, old model continues serving. After swap, new requests use new model.
        """
        import joblib
        try:
            new_checkpoint = joblib.load(new_model_path)

            with self._lock:
                self._model = new_checkpoint['model']
                self._label_encoder = new_checkpoint['label_encoder']
                self._version = new_checkpoint['version']

            logger.info(f"Hot swap completed: version={self._version}")
            return True
        except Exception as e:
            logger.error(f"Hot swap failed: {e}")
            return False

    async def predict(self, text: str) -> Tuple[str, float]:
        """
        Lock-free inference: get model reference first, then do Ollama call + sklearn inference outside lock.
        Returns (label, confidence).
        """
        with self._lock:
            if self._model is None or self._label_encoder is None:
                return "未知", 0.0
            current_model = self._model
            current_encoder = self._label_encoder

        try:
            import httpx
            import numpy as np

            OLLAMA_API_URL = "http://localhost:11434/api/embed"
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    OLLAMA_API_URL,
                    json={"model": "bge-m3", "input": [text]}
                )
                response.raise_for_status()
                embeddings = response.json().get('embeddings', [])
                embedding = np.array(embeddings[0], dtype=np.float32)

            pred_id = current_model.predict([embedding])[0]
            probabilities = current_model.predict_proba([embedding])[0]
            confidence = float(max(probabilities))
            label = current_encoder.inverse_transform([pred_id])[0]

            return label, confidence
        except Exception as e:
            logger.error(f"Classification inference failed: {e}")
            return "未知", 0.0

    @property
    def version(self) -> Optional[str]:
        return self._version


class ClassificationModel:
    """Local classification model (XGBoost or Linear)."""

    def __init__(
        self,
        model_type: str = "xgboost",  # "xgboost" or "linear"
        model_path: Optional[str] = None,
        label_encoder_path: Optional[str] = None
    ):
        """
        Initialize classification model.

        Args:
            model_type: 'xgboost' or 'linear'
            model_path: Path to saved model file
            label_encoder_path: Path to label encoder
        """
        self.model_type = model_type
        self.model_path = model_path
        self.label_encoder_path = label_encoder_path
        self._model = None
        self._label_encoder = None

    def load(self):
        """Load model from disk."""
        if self._model is not None:
            return

        if self.model_path and os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    self._model = pickle.load(f)
                logger.info(f"Classification model loaded from {self.model_path}")
            except Exception as e:
                logger.warning(f"Failed to load model: {e}")
                self._model = None

        if self.label_encoder_path and os.path.exists(self.label_encoder_path):
            try:
                with open(self.label_encoder_path, 'rb') as f:
                    self._label_encoder = pickle.load(f)
                logger.info(f"Label encoder loaded from {self.label_encoder_path}")
            except Exception as e:
                logger.warning(f"Failed to load label encoder: {e}")

        if self._model is None:
            logger.info("Using demo mode classification (mock)")

    def predict(self, X) -> List[str]:
        """
        Predict class labels.

        Args:
            X: Feature vectors (2D array)

        Returns:
            List of predicted labels
        """
        if self._model is None:
            logger.warning("Model not loaded, returning demo predictions")
            return ["NORMAL"] * len(X) if hasattr(X, '__len__') else ["NORMAL"]

        self.load()

        try:
            if hasattr(self._model, 'predict'):
                predictions = self._model.predict(X)
                if self._label_encoder:
                    predictions = self._label_encoder.inverse_transform(predictions)
                return predictions.tolist() if hasattr(predictions, 'tolist') else list(predictions)
        except Exception as e:
            logger.error(f"Prediction failed: {e}")

        return ["NORMAL"] * len(X) if hasattr(X, '__len__') else ["NORMAL"]

    def predict_proba(self, X) -> List[List[float]]:
        """
        Predict class probabilities.

        Args:
            X: Feature vectors

        Returns:
            List of probability arrays
        """
        if self._model is None:
            return [[1.0]]  # demo mode

        self.load()

        try:
            if hasattr(self._model, 'predict_proba'):
                probs = self._model.predict_proba(X)
                return probs.tolist() if hasattr(probs, 'tolist') else list(probs)
        except Exception as e:
            logger.error(f"Probability prediction failed: {e}")

        return [[1.0]]

    def fit(self, X, y, **kwargs):
        """Train the model (for future use)."""
        self.load()

        if self._model is None:
            if self.model_type == "xgboost":
                try:
                    import xgboost as xgb
                    self._model = xgb.XGBClassifier(**kwargs)
                    self._model.fit(X, y)
                    logger.info("XGBoost model trained")
                except ImportError:
                    logger.error("XGBoost not installed")
            else:
                try:
                    from sklearn.linear_model import LogisticRegression
                    self._model = LogisticRegression(**kwargs)
                    self._model.fit(X, y)
                    logger.info("Linear model trained")
                except ImportError:
                    logger.error("sklearn not installed")

    def save(self, path: str):
        """Save model to disk."""
        if self._model is None:
            logger.warning("No model to save")
            return

        with open(path, 'wb') as f:
            pickle.dump(self._model, f)
        logger.info(f"Model saved to {path}")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None