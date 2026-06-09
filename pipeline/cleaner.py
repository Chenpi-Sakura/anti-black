"""
Cleaning module for AntiBlack pipeline.
Handles message cleaning and normalization.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Set
import hashlib

logger = logging.getLogger(__name__)

# 防御性编程：超长消息直接丢弃（DoS 防护）
MAX_TEXT_LENGTH = 10_000


class CleanedMessage:
    """Cleaned message object."""

    def __init__(
        self,
        message_id: str,
        source_channel: str,
        group_id: str,
        author_id: str,
        cleaned_text: str,
        original_text: str,
        published_at: str,
        metadata: Dict[str, Any] = None
    ):
        self.message_id = message_id
        self.source_channel = source_channel
        self.group_id = group_id
        self.author_id = author_id
        self.cleaned_text = cleaned_text
        self.original_text = original_text
        self.published_at = published_at
        self.metadata = metadata or {}


class Cleaner:
    """Message cleaner with deduplication."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.dedup_window_hours = self.config.get('cleaning', {}).get('dedup_window_hours', 24)
        self.simhash_threshold = self.config.get('cleaning', {}).get('simhash_threshold', 12)

        # In-memory deduplication cache
        self._exact_hash_cache: Set[str] = set()
        self._simhash_cache: Dict[str, int] = {}

        # Noise patterns
        self._noise_patterns = [
            r'^测试\d+$',
            r'^\d+$',
            r'^[^\w一-鿿]+$',  # Only symbols
        ]

    def clean(self, raw_messages: List[Dict[str, Any]]) -> List[CleanedMessage]:
        """Clean a list of raw messages."""
        cleaned = []

        for raw in raw_messages:
            try:
                cleaned_msg = self._clean_single(raw)
                if cleaned_msg:
                    cleaned.append(cleaned_msg)
            except Exception as e:
                logger.error(f"Error cleaning message {raw.get('message_id')}: {e}")

        return cleaned

    def _clean_single(self, raw: Dict[str, Any]) -> Optional[CleanedMessage]:
        """Clean a single message."""
        message_id = raw.get('message_id', '')
        original_text = raw.get('raw_text', '')

        # Skip empty messages
        if not original_text or not original_text.strip():
            return None

        # DoS 防护：超长消息直接丢弃
        if len(original_text) > MAX_TEXT_LENGTH:
            logger.warning(f"Message exceeds MAX_TEXT_LENGTH ({len(original_text)} > {MAX_TEXT_LENGTH}): {message_id}")
            return None

        # Normalize text
        cleaned_text = self._normalize_text(original_text)

        # Check for noise
        if self._is_noise(cleaned_text):
            return None

        # NOTE: Deduplication is now enabled to prevent redundant LLM processing
        # Exact deduplication
        text_hash = self._compute_text_hash(cleaned_text)
        if text_hash in self._exact_hash_cache:
            logger.debug(f"Duplicate exact hash: {message_id}")
            return None

        # Approximate deduplication
        simhash = self._compute_simhash(cleaned_text)
        if self._is_approx_duplicate(simhash):
            logger.debug(f"Duplicate simhash: {message_id}")
            return None

        # Add to caches
        self._exact_hash_cache.add(text_hash)
        self._simhash_cache[text_hash] = simhash

        # Limit cache size
        if len(self._exact_hash_cache) > 100000:
            self._trim_cache()

        return CleanedMessage(
            message_id=message_id,
            source_channel=raw.get('source_channel', ''),
            group_id=raw.get('group_id', ''),
            author_id=raw.get('author_id', ''),
            cleaned_text=cleaned_text,
            original_text=original_text,
            published_at=raw.get('published_at', ''),
            metadata=raw.get('metadata', {})
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text."""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Convert full-width to half-width
        text = text.translate(str.maketrans(
            'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９',
            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        ))

        # Normalize Unicode
        text = text.replace('　', ' ')  # Full-width space
        text = text.replace('\xa0', ' ')     # Non-breaking space

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def _is_noise(self, text: str) -> bool:
        """Check if text is noise."""
        # Too short
        if len(text) < 3:
            return True

        # Match noise patterns
        for pattern in self._noise_patterns:
            if re.match(pattern, text):
                return True

        return False

    def _compute_text_hash(self, text: str) -> str:
        """Compute MD5 hash."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def _compute_simhash(self, text: str) -> int:
        """Compute SimHash for Chinese text.

        Uses character-level (1-gram) tokenization since the default
        Simhash tokenizer splits on whitespace, which treats an entire
        Chinese sentence as a single token.
        """
        from simhash import Simhash
        return Simhash(list(text)).value

    def _is_approx_duplicate(self, simhash: int) -> bool:
        """Check if simhash is approximate duplicate."""
        for cached_hash in self._simhash_cache.values():
            if self._hamming_distance(simhash, cached_hash) <= self.simhash_threshold:
                return True
        return False

    def _hamming_distance(self, hash1: int, hash2: int) -> int:
        """Calculate Hamming distance."""
        xor = hash1 ^ hash2
        return bin(xor).count('1')

    def _trim_cache(self) -> None:
        """Trim caches to limit memory usage."""
        # Remove oldest half
        if len(self._exact_hash_cache) > 100000:
            remove_count = len(self._exact_hash_cache) // 2
            keys_to_remove = list(self._exact_hash_cache)[:remove_count]
            for key in keys_to_remove:
                self._exact_hash_cache.discard(key)
                self._simhash_cache.pop(key, None)