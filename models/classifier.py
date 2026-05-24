"""
Classification model using XGBoost or sklearn linear classifier.
"""
import os
import pickle
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


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