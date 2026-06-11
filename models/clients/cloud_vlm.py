"""
Cloud VLM client for Alibaba DashScope (Qwen-VL series).
Uses OpenAI-compatible API for cloud-based vision language models.
"""
import os
import base64
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class CloudVLMClient:
    """Client for cloud VLM APIs (DashScope Qwen-VL)."""

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 120
    ):
        """
        Initialize cloud VLM client.

        All model / base / key values fall back to env (CLOUD_VLM_API_BASE /
        CLOUD_VLM_API_KEY / CLOUD_VLM_MODEL) and finally to a placeholder
        default so the client can be constructed even without configuration
        (it will fail at call time, not at construction time).

        Args:
            api_base: API base URL (default: $CLOUD_VLM_API_BASE or DashScope)
            api_key: API key (default: $CLOUD_VLM_API_KEY or $DASHSCOPE_API_KEY)
            model: VLM model name (default: $CLOUD_VLM_MODEL or qwen2.5-vl-32b)
            timeout: Request timeout in seconds
        """
        self.api_base = (
            api_base
            or os.environ.get("CLOUD_VLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("CLOUD_VLM_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
        )
        self.model = model or os.environ.get("CLOUD_VLM_MODEL", "qwen2.5-vl-32b")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if cloud VLM API is available."""
        try:
            import openai
            return True
        except ImportError:
            return False

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
        Analyze image using cloud VLM.

        Args:
            image_path: Path to image file
            prompt: Question/prompt about the image
            model: VLM model name (uses default if None)

        Returns:
            Description/analysis of the image
        """
        from openai import OpenAI

        model = model or self.model
        image_b64 = self._encode_image_to_base64(image_path)

        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.api_base
            )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                timeout=self.timeout
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Cloud VLM analysis failed: {e}")
            return f"Error: {str(e)}"

    def analyze_image_bytes(
        self,
        image_bytes: bytes,
        prompt: str = "描述这张图片的内容",
        model: Optional[str] = None
    ) -> str:
        """
        Analyze image from bytes using cloud VLM.

        Args:
            image_bytes: Image data as bytes
            prompt: Question/prompt about the image
            model: VLM model name

        Returns:
            Description/analysis of the image
        """
        from openai import OpenAI

        model = model or self.model
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.api_base
            )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                timeout=self.timeout
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Cloud VLM analysis failed: {e}")
            return f"Error: {str(e)}"

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
        from openai import OpenAI

        model = model or self.model

        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.api_base
            )

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=self.timeout
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Cloud VLM chat failed: {e}")
            return f"Error: {str(e)}"
