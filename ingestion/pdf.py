"""
ingestion.pdf — Parse PDF documents page by page.

Uses PyPDF2 for lightweight, dependency-free PDF text extraction.
Each page is yielded as a separate document to keep chunk boundaries clean.
"""

import datetime
import sys
from pathlib import Path
from typing import Dict, Generator


def parse_pdf(filepath: Path) -> Generator[Dict, None, None]:
    """
    Extract text from a PDF file, yielding one document per page.
    Pages with negligible text (< 20 chars) are skipped.
    """
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        print(
            "[ingestion.pdf] PyPDF2 not installed. Run: pip install PyPDF2",
            file=sys.stderr,
        )
        return

    try:
        reader = PdfReader(str(filepath))
        total_pages = len(reader.pages)

        mtime = filepath.stat().st_mtime
        timestamp = datetime.datetime.fromtimestamp(mtime).isoformat()

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            if not text or len(text.strip()) < 20:
                continue

            yield {
                "text": text.strip(),
                "source": f"{filepath.name} (p.{page_num}/{total_pages})",
                "timestamp": timestamp,
                "tags": "pdf,document",
            }

    except Exception as e:
        print(f"[ingestion.pdf] Error reading {filepath}: {e}", file=sys.stderr)
