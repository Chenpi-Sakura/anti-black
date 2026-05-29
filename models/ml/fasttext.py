"""
FastText model for language detection.
"""
import os
import re
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class FastTextModel:
    """Local FastText model for language detection."""

    # Language codes supported
    SUPPORTED_LANGUAGES = {
        'zh', 'en', 'ja', 'ko', 'vi', 'th', 'ms', 'id', 'tl', 'km', 'lo', 'my'
    }

    def __init__(
        self,
        model_path: Optional[str] = None,
        lid_code: str = "lid.176.bin"  # FastText language identification model
    ):
        """
        Initialize FastText model.

        Args:
            model_path: Path to FastText .bin model file
            lid_code: Default lid model name to download
        """
        self.model_path = model_path
        self.lid_code = lid_code
        self._model = None

    def load(self):
        """Load FastText model."""
        if self._model is not None:
            return

        # Try to load from specified path
        if self.model_path and os.path.exists(self.model_path):
            try:
                import fasttext
                self._model = fasttext.load_model(self.model_path)
                logger.info(f"FastText model loaded from {self.model_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load FastText model: {e}")

        # Try common locations
        default_paths = [
            os.path.join(os.path.expanduser("~"), ".fasttext", self.lid_code),
            os.path.join(os.getcwd(), "models", self.lid_code),
        ]

        for path in default_paths:
            if os.path.exists(path):
                try:
                    import fasttext
                    self._model = fasttext.load_model(path)
                    logger.info(f"FastText model loaded from {path}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load from {path}: {e}")

        logger.info("FastText model not available, using rule-based language detection")

    def detect_language(self, text: str) -> str:
        """
        Detect language of input text.

        Args:
            text: Input text

        Returns:
            Language code (e.g., 'zh', 'en')
        """
        if self._model is not None:
            try:
                self.load()
                lang = self._model.predict(text.replace("\n", " "), k=1)[0][0]
                return lang.replace("__label__", "")
            except Exception as e:
                logger.warning(f"FastText detection failed: {e}")

        # Fallback: rule-based detection
        return self._rule_based_detect(text)

    def _rule_based_detect(self, text: str) -> str:
        """Rule-based language detection fallback."""
        if not text or len(text.strip()) == 0:
            return "unknown"

        # Count characters in different scripts
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        japanese_chars = len(re.findall(r'[぀-ゟ゠-ヿ]', text))
        korean_chars = len(re.findall(r'[가-힯]', text))
        thai_chars = len(re.findall(r'[฀-๿]', text))
        vietnamese_marks = len(re.findall(r'[ăâàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]', text, re.I))

        total_chars = len(text.replace(" ", ""))

        # Determine language by character ratio
        if total_chars == 0:
            return "unknown"

        if chinese_chars / total_chars > 0.3:
            return "zh"
        if japanese_chars / total_chars > 0.3:
            return "ja"
        if korean_chars / total_chars > 0.3:
            return "ko"
        if thai_chars / total_chars > 0.3:
            return "th"
        if vietnamese_marks / total_chars > 0.1:
            return "vi"

        # Check for Latin script (English or others)
        latin_chars = len(re.findall(r'[a-zA-Z]', text))
        if latin_chars / total_chars > 0.5:
            return "en"

        return "unknown"

    def detect_batch(self, texts: List[str]) -> List[str]:
        """Detect languages for a batch of texts."""
        return [self.detect_language(t) for t in texts]

    @property
    def is_loaded(self) -> bool:
        return self._model is not None