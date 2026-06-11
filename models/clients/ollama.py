"""
Ollama client for VLM (Qwen2-VL) and Embedding inference.
VLM handles image understanding, Embedding for text vectorization.
LLM uses cloud OpenAI API.
"""
import os
import base64
import logging
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for Ollama API (VLM and Embedding only - LLM uses cloud)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        vlm_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        timeout: int = 120
    ):
        """
        Initialize Ollama client.

        All model / URL values fall back to env (OLLAMA_BASE_URL /
        OLLAMA_VLM_MODEL / OLLAMA_LLM_MODEL / OLLAMA_EMBEDDING_MODEL) and
        finally to a placeholder default so the client can be constructed
        even without configuration.

        Args:
            base_url: Ollama server URL (default: $OLLAMA_BASE_URL or localhost:11434)
            vlm_model: VLM model name (default: $OLLAMA_VLM_MODEL or qwen2-vl:2b)
            embedding_model: Embedding model name (default: $OLLAMA_EMBEDDING_MODEL or nomic-embed-text)
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.vlm_model = vlm_model or os.environ.get("OLLAMA_VLM_MODEL", "qwen2-vl:2b")
        self.embedding_model = embedding_model or os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if Ollama server is available."""
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [m['name'] for m in data.get('models', [])]
        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
        return []

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode image file to base64 string."""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze_image(
        self,
        image_path: str,
        prompt: str = "描述这张图片的内容",
        model: Optional[str] = None
    ) -> str:
        """
        Analyze image using VLM (Qwen2-VL).

        Args:
            image_path: Path to image file
            prompt: Question/prompt about the image
            model: VLM model name (uses default if None)

        Returns:
            Description/analysis of the image
        """
        import requests

        model = model or self.vlm_model

        try:
            image_b64 = self._encode_image_to_base64(image_path)

            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json().get('response', '')
            else:
                logger.error(f"VLM request failed: {response.status_code}")
                return f"Error: {response.status_code}"

        except Exception as e:
            logger.error(f"VLM analysis failed: {e}")
            return f"Error: {str(e)}"

    def analyze_image_bytes(
        self,
        image_bytes: bytes,
        prompt: str = "描述这张图片的内容",
        model: Optional[str] = None
    ) -> str:
        """
        Analyze image from bytes using VLM.

        Args:
            image_bytes: Image data as bytes
            prompt: Question/prompt about the image
            model: VLM model name

        Returns:
            Description/analysis of the image
        """
        import requests

        model = model or self.vlm_model

        try:
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json().get('response', '')
            else:
                logger.error(f"VLM request failed: {response.status_code}")
                return f"Error: {response.status_code}"

        except Exception as e:
            logger.error(f"VLM analysis failed: {e}")
            return f"Error: {str(e)}"

    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """
        Get embeddings from Ollama.

        Args:
            text: Input text to embed
            model: Embedding model name (uses default if None)

        Returns:
            Embedding vector (list of floats)
        """
        import requests

        model = model or self.embedding_model

        try:
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=30
            )

            if response.status_code == 200:
                return response.json().get('embedding', [])
        except Exception as e:
            logger.warning(f"Ollama embedding failed: {e}")

        return [0.0] * 768  # fallback zero vector

    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """
        Get embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            model: Embedding model name

        Returns:
            List of embedding vectors
        """
        return [self.embed(text, model) for text in texts]

    def vlm_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None
    ) -> str:
        """
        Chat with VLM using multi-modal messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
                     Content can include image URLs (base64 data URIs)
            model: VLM model name

        Returns:
            Assistant response
        """
        import requests

        model = model or self.vlm_model

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json().get('message', {}).get('content', '')
            else:
                logger.error(f"VLM chat failed: {response.status_code}")
                return f"Error: {response.status_code}"

        except Exception as e:
            logger.error(f"VLM chat failed: {e}")
            return f"Error: {str(e)}"