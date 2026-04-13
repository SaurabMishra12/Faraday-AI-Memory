"""
ingestion — Multi-format document parser package.

Each parser is a generator that yields standardized document dicts:
    {"text": str, "source": str, "timestamp": str, "tags": str}

The `process_file` router dispatches files to the correct parser
based on extension and filename heuristics.
"""

from pathlib import Path
from typing import Dict, Generator

from .markdown import parse_markdown
from .chatgpt import parse_chatgpt_export
from .gemini import parse_gemini_html
from .pdf import parse_pdf
from .image import parse_image


def process_file(filepath: Path) -> Generator[Dict, None, None]:
    """
    Route a file to the appropriate parser based on extension
    and filename heuristics.  Yields standardized document dicts.
    """
    ext = filepath.suffix.lower()
    name = filepath.name.lower()

    # ChatGPT JSON export
    if ext == ".json" and "conversations" in name:
        yield from parse_chatgpt_export(filepath)

    # Gemini HTML takeout
    elif ext == ".html" and ("activity" in name or "gemini" in name):
        yield from parse_gemini_html(filepath)

    # PDF documents
    elif ext == ".pdf":
        yield from parse_pdf(filepath)

    # Images (OCR)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"):
        yield from parse_image(filepath)

    # Markdown / plain text (default)
    elif ext in (".md", ".txt", ".rst", ".log", ".csv"):
        yield from parse_markdown(filepath)

    # Unknown — attempt as plain text
    else:
        try:
            yield from parse_markdown(filepath)
        except Exception:
            pass
