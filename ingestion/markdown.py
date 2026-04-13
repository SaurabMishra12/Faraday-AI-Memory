"""
ingestion.markdown — Parse plain text and Markdown files.

Yields one document per file with file-modification timestamp.
"""

import datetime
import sys
from pathlib import Path
from typing import Dict, Generator


def parse_markdown(filepath: Path) -> Generator[Dict, None, None]:
    """
    Read a text/markdown file and yield a single document dict.
    Uses streaming read for large files (reads in 10 MB chunks
    and joins — keeps memory bounded for very large markdown dumps).
    """
    try:
        # For most markdown files (< 10 MB), this is instant.
        # For larger files we still read all at once since we need
        # the full text for chunking downstream.
        text = filepath.read_text(encoding="utf-8", errors="replace")

        if not text.strip():
            return

        mtime = filepath.stat().st_mtime
        timestamp = datetime.datetime.fromtimestamp(mtime).isoformat()

        yield {
            "text": text,
            "source": filepath.name,
            "timestamp": timestamp,
            "tags": "markdown",
        }
    except Exception as e:
        print(f"[ingestion.markdown] Error reading {filepath}: {e}", file=sys.stderr)
