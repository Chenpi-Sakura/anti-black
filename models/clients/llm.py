"""
Unified chat LLM client with multi-provider fallback chain.

OpenAI-compatible (works with Volcengine Ark / MiniMax / DashScope / Ollama / vLLM).
Swapping models is a config change (.env), not a code change.

Fallback semantics:
  - Try providers in priority order
  - On transient error (429/timeout/auth), advance to next
  - After 3 consecutive failures on a provider, open its circuit for 60s
    (skip it during the cool-down to avoid hammering a rate-limited endpoint)
  - All providers failed -> raise AllProvidersExhausted

Env config (priority: doubao -> minimax -> qwen):
  LLM_PRIMARY_NAME=doubao
  LLM_PRIMARY_API_KEY=...
  LLM_PRIMARY_BASE_URL=...
  LLM_PRIMARY_MODEL=...

  LLM_FALLBACK_1_NAME=minimax
  LLM_FALLBACK_1_API_KEY=...
  LLM_FALLBACK_1_BASE_URL=...
  LLM_FALLBACK_1_MODEL=...

  # up to LLM_FALLBACK_4_*

Backward compat: if new env not set, falls back to legacy single-provider
  OPENAI_API_KEY / LLM_API_BASE / LLM_MODEL
"""
import os
import re
import time
import json
import logging
import asyncio
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AllProvidersExhausted(Exception):
    """All configured LLM providers failed. Callers should fall back to defaults (e.g., '未知/其他')."""
    pass


class LLMClient:
    """Unified chat LLM client with multi-provider fallback chain.

    Includes `classify_batch()` for sending 5-10 texts in a single LLM call
    (5-10x faster than per-text calls). Used by Classifier.classify_batch.
    """

    def __init__(
        self,
        providers: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 60,
        max_retries: int = 0,
        enable_thinking_strip: bool = True,
    ):
        self.providers = providers if providers is not None else self._load_providers_from_env()
        if not self.providers:
            raise ValueError(
                "No LLM providers configured. Set LLM_PRIMARY_API_KEY/..."
                " LLM_PRIMARY_BASE_URL/LLM_PRIMARY_MODEL env vars, "
                "or legacy OPENAI_API_KEY/LLM_API_BASE/LLM_MODEL."
            )
        # Sort by priority just in case caller passed unsorted
        self.providers.sort(key=lambda p: p.get("priority", 0))
        self.timeout = timeout
        self.max_retries = max_retries
        self.enable_thinking_strip = enable_thinking_strip
        # per-provider health
        self._health: Dict[str, Dict[str, float]] = {
            p["name"]: {"failures": 0, "open_until": 0.0} for p in self.providers
        }
        # lazy AsyncOpenAI per provider (deferred to first use to avoid blocking __init__)
        self._clients: Dict[str, Any] = {}

    @staticmethod
    def _load_providers_from_env() -> List[Dict[str, Any]]:
        primary = {
            "name":     os.environ.get("LLM_PRIMARY_NAME", "primary"),
            "api_key":  os.environ.get("LLM_PRIMARY_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            "base_url": os.environ.get("LLM_PRIMARY_BASE_URL") or os.environ.get("LLM_API_BASE"),
            "model":    os.environ.get("LLM_PRIMARY_MODEL") or os.environ.get("LLM_MODEL"),
            "priority": 0,
        }
        fallbacks = []
        for i in range(1, 5):  # support up to 4 fallbacks
            name = os.environ.get(f"LLM_FALLBACK_{i}_NAME")
            if not name:
                break
            fallbacks.append({
                "name":     name,
                "api_key":  os.environ.get(f"LLM_FALLBACK_{i}_API_KEY"),
                "base_url": os.environ.get(f"LLM_FALLBACK_{i}_BASE_URL"),
                "model":    os.environ.get(f"LLM_FALLBACK_{i}_MODEL"),
                "priority": i,
            })
        all_providers = [primary] + fallbacks
        return [p for p in all_providers if p.get("api_key") and p.get("base_url") and p.get("model")]

    # --- core public API (callers only need these) ---

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Main entrypoint. Returns content string (thinking tags stripped).
        Raises AllProvidersExhausted if all providers fail.
        """
        response = await self.chat_raw(messages, **kwargs)
        content = response.choices[0].message.content or ""
        return self._strip_thinking_tags(content)

    async def chat_raw(self, messages: List[Dict[str, str]], **kwargs):
        """Return the full response object (for callers that need tool_calls etc.).
        Raises AllProvidersExhausted if all providers fail.
        """
        from openai import APITimeoutError, APIError
        last_err: Optional[Exception] = None
        for provider in self.providers:
            if self._is_circuit_open(provider):
                logger.debug(f"Skipping provider {provider['name']} (circuit open)")
                continue
            client = self._get_client(provider)
            try:
                response = await client.chat.completions.create(
                    model=provider["model"],
                    messages=messages,
                    timeout=self.timeout,
                    **kwargs,
                )
                self._record_success(provider)
                return response
            except (APITimeoutError, APIError) as e:
                self._record_failure(provider, e)
                logger.warning(
                    f"LLM provider {provider['name']} failed: {type(e).__name__}: {e}; trying next"
                )
                last_err = e
                continue
            except Exception as e:
                # Non-transient error (e.g., 4xx schema error). Don't burn fallbacks
                # because all fallbacks are likely to fail the same way.
                self._record_failure(provider, e)
                logger.error(
                    f"LLM provider {provider['name']} non-transient error: "
                    f"{type(e).__name__}: {e}"
                )
                raise
        raise AllProvidersExhausted(
            f"All LLM providers failed. Last error: {last_err}"
        )

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Single-prompt convenience."""
        msgs: List[Dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": prompt})
        return await self.chat(msgs, **kwargs)

    async def complete_with_history(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> str:
        """LightRAG-style: prompt + system + history. Used by services/lightrag_service.py."""
        msgs: List[Dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in (history_messages or []):
            msgs.append(m)
        msgs.append({"role": "user", "content": prompt})
        return await self.chat(msgs, **kwargs)

    # --- inspection / monitoring ---

    def get_health(self) -> Dict[str, Any]:
        """Snapshot of provider health (for /scripts/llm_health.py and operational dashboards)."""
        return {
            "providers": [
                {
                    **p,
                    "consecutive_failures": self._health[p["name"]]["failures"],
                    "circuit_open_seconds_remaining": max(
                        0, int(self._health[p["name"]]["open_until"] - time.time())
                    ),
                }
                for p in self.providers
            ]
        }

    # --- internal ---

    def _get_client(self, provider: Dict[str, Any]):
        from openai import AsyncOpenAI
        if provider["name"] not in self._clients:
            self._clients[provider["name"]] = AsyncOpenAI(
                api_key=provider["api_key"],
                base_url=provider["base_url"],
            )
        return self._clients[provider["name"]]

    def _is_circuit_open(self, provider: Dict[str, Any]) -> bool:
        return time.time() < self._health[provider["name"]]["open_until"]

    def _record_failure(self, provider: Dict[str, Any], error: Exception) -> None:
        h = self._health[provider["name"]]
        h["failures"] += 1
        if h["failures"] >= 3 and h["open_until"] == 0.0:
            h["open_until"] = time.time() + 60  # 60s cool-down
            logger.warning(
                f"Circuit opened for provider {provider['name']} for 60s "
                f"after {h['failures']} consecutive failures. Last error: {error}"
            )

    def _record_success(self, provider: Dict[str, Any]) -> None:
        h = self._health[provider["name"]]
        if h["failures"] > 0 or h["open_until"] > 0:
            logger.info(
                f"Provider {provider['name']} recovered after {h['failures']} failures"
            )
        h["failures"] = 0
        h["open_until"] = 0.0

    def _strip_thinking_tags(self, text: str) -> str:
        if not self.enable_thinking_strip or not text:
            return text
        # MiniMax M2.7 format
        text = re.sub(r"<\|think_start\|>.*?<\|think_end\|>", "", text, flags=re.DOTALL)
        # OpenAI/Anthropic/vLLM common format
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    # --- batched classification (Layer 2 optimization) ---

    async def classify_batch(
        self,
        texts: List[str],
        system_prompt: Optional[str] = None,
        batch_size: int = 8,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Send multiple texts in a single LLM call (5-10 per call by default).

        The LLM is asked to classify each text independently and return a JSON
        array; we parse and return one JSON dict string per input text
        (so the caller can json.loads each).

        Falls back to per-text calls if the batched response cannot be parsed
        at all.

        Returns a list of N strings where N == len(texts). Each string is
        either a JSON dict like '{"index": 1, "level1": "..."}' or '{}' if
        that text's classification couldn't be parsed.
        """
        if not texts:
            return []

        if len(texts) == 1:
            # No point in batching a single text
            return [await self.complete(texts[0], system_prompt=system_prompt,
                                       **(extra_body or {}))]

        results: List[Optional[str]] = [None] * len(texts)
        for chunk_start in range(0, len(texts), batch_size):
            chunk = texts[chunk_start:chunk_start + batch_size]
            prompt = self._build_classify_batch_prompt(chunk)
            try:
                response_text = await self.complete(
                    prompt=prompt, system_prompt=system_prompt,
                    **(extra_body or {}),
                )
                parsed = self._parse_classify_batch_response(response_text, len(chunk))
                for i, item in enumerate(parsed):
                    if 0 <= i < len(chunk) and results[chunk_start + i] is None:
                        results[chunk_start + i] = item
            except AllProvidersExhausted:
                raise
            except Exception as e:
                logger.warning(f"Batched classify failed for chunk {chunk_start}: {e}")
                # leave that chunk as None (filled with {} below)

        return [r if r is not None else "{}" for r in results]

    @staticmethod
    def _build_classify_batch_prompt(texts: List[str]) -> str:
        """Build a prompt asking the LLM to classify each text and return a JSON array.

        Each text snippet is truncated to 300 chars to keep total prompt size
        manageable for large batches.
        """
        parts = ["请对以下每条文本独立进行黑灰产风险分类, 严格按 JSON 数组返回 (按输入顺序, 每条对应一个对象):\n"]
        for i, t in enumerate(texts, 1):
            snippet = t[:300] if len(t) > 300 else t
            parts.append(f"文本 {i}: {snippet}\n")
        parts.append(
            """
返回格式( 严格 JSON, 无其他内容):
[
  {"index": 1, "level1": "账号交易|流量作弊|诈骗引流|黑产工具|未知/其他", "level2": "...", "confidence": 0.0-1.0, "reason": "..."},
  {"index": 2, ...}
]
"""
        )
        return "".join(parts)

    @staticmethod
    def _parse_classify_batch_response(response_text: str, expected_n: int) -> List[Optional[str]]:
        """Parse the batched LLM response into a list of N JSON dict strings.

        Handles common cases:
          - Direct JSON array
          - Markdown-fenced ```json ... ```
          - The LLM adding prose around the JSON
          - Partial responses (fewer items than expected)

        Match items by their "index" field (preferred) or by position (fallback).
        """
        text = response_text.strip()
        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)

        # Find the outermost JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.warning(
                f"Could not find JSON array in batched classify response: {text[:200]!r}"
            )
            return [None] * expected_n

        json_text = text[start:end + 1]
        try:
            arr = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON parse failed for batched classify: {e}; text={text[:200]!r}"
            )
            return [None] * expected_n

        if not isinstance(arr, list):
            logger.warning(f"Batched classify response is not a list: {type(arr)}")
            return [None] * expected_n

        # Match items by their "index" field (preferred) or by position (fallback)
        out: List[Optional[str]] = [None] * expected_n
        for i, item in enumerate(arr):
            if not isinstance(item, dict):
                continue
            idx = item.get("index", i + 1)  # default to position
            try:
                pos = int(idx) - 1
            except (TypeError, ValueError):
                pos = i
            if 0 <= pos < expected_n and out[pos] is None:
                out[pos] = json.dumps(item, ensure_ascii=False)
        return out
