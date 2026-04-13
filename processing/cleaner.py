"""
processing.cleaner — Text normalization and deduplication hashing.

Handles:
  - Unicode normalization (NFC)
  - HTML tag stripping
  - Control character removal
  - Excessive whitespace collapse
  - Minimum length filtering
  - SHA-256 content hashing for deduplication
"""

import hashlib
import re
import unicodedata
from typing import Optional


def clean_text(text: str) -> Optional[str]:
    """
    Normalize and clean text for embedding.

    Returns cleaned text, or None if the result is too short
    to be meaningful (< 30 characters after cleaning).
    """
    if not text:
        return None

    # 1. Unicode normalize to NFC (compose characters)
    text = unicodedata.normalize("NFC", text)

    # 2. Strip residual HTML tags (from Gemini exports, etc.)
    text = re.sub(r"<[^>]+>", " ", text)

    # 3. Remove control characters (except newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # 4. Collapse excessive newlines (3+ → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 5. Collapse excessive spaces (3+ → 2)
    text = re.sub(r" {3,}", "  ", text)

    # 6. Strip leading/trailing whitespace
    text = text.strip()

    # 7. Minimum length gate
    if len(text) < 30:
        return None

    return text


def compute_hash(content: str) -> str:
    """
    Generate a deterministic SHA-256 hash for content deduplication.
    Two identical chunks will always produce the same hash,
    preventing re-embedding on repeated updates.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
