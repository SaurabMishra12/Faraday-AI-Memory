"""
processing.chunker — Paragraph-aware text chunker with overlap.

Splits text into ~300-word chunks, preferring paragraph boundaries.
Falls back to word-level splitting for very long paragraphs.
Maintains configurable word overlap between adjacent chunks
to preserve context continuity for embeddings.
"""

import re
from typing import List


def chunk_text(
    text: str,
    max_words: int = 300,
    overlap: int = 50,
    min_chunk_words: int = 15,
) -> List[str]:
    """
    Split text into chunks of approximately `max_words`, aligned
    to paragraph boundaries where possible.

    Args:
        text:            Input text to chunk.
        max_words:       Target maximum words per chunk.
        overlap:         Words of overlap between consecutive chunks.
        min_chunk_words: Discard trailing chunks smaller than this.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    chunks: List[str] = []

    # Step 1: Split into paragraphs (double-newline separated)
    paragraphs = re.split(r"\n\n+", text)

    current_words: List[str] = []
    current_len = 0

    for para in paragraphs:
        words = para.split()
        if not words:
            continue

        # If this paragraph fits in the current chunk, append it
        if current_len + len(words) <= max_words:
            current_words.extend(words)
            current_len += len(words)
        else:
            # Flush current chunk if it has content
            if current_words:
                chunks.append(" ".join(current_words))
                # Retain overlap from end of current chunk
                if overlap > 0:
                    current_words = current_words[-overlap:]
                    current_len = len(current_words)
                else:
                    current_words = []
                    current_len = 0

            # If paragraph itself exceeds max_words, split strictly
            if len(words) > max_words:
                i = 0
                while i < len(words):
                    sub = words[i : i + max_words]
                    chunks.append(" ".join(sub))
                    step = max(1, max_words - overlap)
                    i += step
                # Reset after processing oversized paragraph
                current_words = []
                current_len = 0
            else:
                current_words.extend(words)
                current_len += len(words)

    # Flush remaining words if they form a meaningful chunk
    if current_words and len(current_words) >= min_chunk_words:
        chunks.append(" ".join(current_words))

    return chunks
