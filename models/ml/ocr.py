"""
OCR model using PaddleOCR.
"""
import os
import logging
from typing import Optional, List, Tuple, Union
from pathlib import Path

logger = logging.getLogger(__name__)


class OCRModel:
    """Local OCR model using PaddleOCR."""

    def __init__(
        self,
        use_angle_cls: bool = True,
        lang: str = "ch",  # 'ch', 'en', 'japan', 'korean'
        device: str = "cpu",  # 'cpu', 'gpu', 'gpu:0'
        det_model_dir: Optional[str] = None,
        rec_model_dir: Optional[str] = None,
        cls_model_dir: Optional[str] = None
    ):
        """
        Initialize OCR model.

        Args:
            use_angle_cls: Use angle classification
            lang: Language ('ch', 'en', 'japan', 'korean', 'chinese_cht')
            device: Device to use ('cpu', 'gpu', 'mps')
            det_model_dir: Custom detection model path
            rec_model_dir: Custom recognition model path
            cls_model_dir: Custom classification model path
        """
        self.use_angle_cls = use_angle_cls
        self.lang = lang
        self.device = device
        self.det_model_dir = det_model_dir
        self.rec_model_dir = rec_model_dir
        self.cls_model_dir = cls_model_dir
        self._ocr = None

    def load(self):
        """Load PaddleOCR model."""
        if self._ocr is not None:
            return

        try:
            from paddleocr import PaddleOCR

            # Determine device
            device = self.device
            if device == "mps":
                device = "cpu"  # PaddleOCR doesn't support MPS directly

            logger.info(f"Loading PaddleOCR (lang={self.lang}, device={device})")

            self._ocr = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                device=device,
                det_model_dir=self.det_model_dir,
                rec_model_dir=self.rec_model_dir,
                cls_model_dir=self.cls_model_dir,
                show_log=False
            )

            logger.info("PaddleOCR loaded successfully")

        except ImportError:
            logger.warning("PaddleOCR not installed, falling back to Tesseract")
            self._ocr = None
        except Exception as e:
            logger.warning(f"Failed to load PaddleOCR: {e}")
            self._ocr = None

    def extract_text(
        self,
        image_path: Union[str, bytes, "PIL.Image.Image"],
        return_coords: bool = False
    ) -> List[dict]:
        """
        Extract text from image.

        Args:
            image_path: Image path, bytes, or PIL Image
            return_coords: Return bounding box coordinates

        Returns:
            List of dicts with 'text' and optionally 'bbox', 'confidence'
        """
        if self._ocr is None:
            logger.warning("OCR not loaded, returning empty result")
            return []

        self.load()

        try:
            if isinstance(image_path, (str, Path)):
                result = self._ocr.ocr(str(image_path), cls=self.use_angle_cls)
            else:
                import numpy as np
                from PIL import Image

                if isinstance(image_path, bytes):
                    import io
                    image_path = Image.open(io.BytesIO(image_path))

                if isinstance(image_path, Image.Image):
                    image_path = np.array(image_path)

                result = self._ocr.ocr(image_path, cls=self.use_angle_cls)

            # Parse result
            if not result or not result[0]:
                return []

            texts = []
            for line in result[0]:
                if line:
                    bbox = line[0]
                    text = line[1][0]
                    confidence = line[1][1]

                    item = {'text': text, 'confidence': confidence}
                    if return_coords:
                        item['bbox'] = bbox

                    texts.append(item)

            return texts

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return []

    def extract_from_image_path(self, image_path: str) -> str:
        """
        Extract text from image file, return concatenated text.

        Args:
            image_path: Path to image file

        Returns:
            Extracted text as string (newline separated)
        """
        results = self.extract_text(image_path, return_coords=False)
        return "\n".join([r['text'] for r in results])

    def extract_from_bytes(self, image_bytes: bytes) -> str:
        """Extract text from image bytes."""
        results = self.extract_text(image_bytes, return_coords=False)
        return "\n".join([r['text'] for r in results])

    @property
    def is_loaded(self) -> bool:
        return self._ocr is not None

    def unload(self):
        """Unload OCR model."""
        if self._ocr is not None:
            del self._ocr
            self._ocr = None
            logger.info("OCR model unloaded")