import uuid
import hashlib
import struct
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    short_uuid = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


def compute_text_hash(text: str) -> str:
    """Compute MD5 hash of text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def compute_simhash(text: str) -> int:
    """Compute SimHash for approximate deduplication."""
    # Simplified SimHash implementation
    # In production, use a proper SimHash library
    hash_bytes = hashlib.md5(text.encode('utf-8')).digest()
    return struct.unpack('<Q', hash_bytes[:8])[0]


def hamming_distance(hash1: int, hash2: int) -> int:
    """Calculate Hamming distance between two hashes."""
    xor = hash1 ^ hash2
    return bin(xor).count('1')
