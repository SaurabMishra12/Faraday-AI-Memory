"""
ingestion.gemini — Parse Google Gemini takeout HTML exports.

Google Takeout for Gemini produces an "My Activity.html" file
with interaction cards wrapped in `<div class="outer-cell">` elements.
This parser streams through those cards and yields one document
per interaction.
"""

import datetime
import sys
from pathlib import Path
from typing import Dict, Generator


def parse_gemini_html(filepath: Path) -> Generator[Dict, None, None]:
    """
    Parse a Google Takeout Gemini activity HTML file.
    Yields one document per interaction card.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print(
            "[ingestion.gemini] beautifulsoup4 not installed. "
            "Run: pip install beautifulsoup4 lxml",
            file=sys.stderr,
        )
        return

    try:
        html = filepath.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")

        # Google Takeout wraps each interaction in outer-cell divs
        cards = soup.find_all("div", class_="outer-cell")

        if not cards:
            # Fallback: dump entire body text as one document
            raw = soup.get_text(separator="\n\n", strip=True)
            if raw.strip():
                yield {
                    "text": raw,
                    "source": f"Gemini: {filepath.name}",
                    "timestamp": _file_timestamp(filepath),
                    "tags": "gemini,chat",
                }
            return

        for idx, card in enumerate(cards):
            text = card.get_text(separator=" ", strip=True)
            if not text or len(text) < 10:
                continue

            # Attempt to extract timestamp from card content
            # Gemini cards often contain a date string; we try to find it
            timestamp = _extract_card_timestamp(card, filepath)

            yield {
                "text": text,
                "source": f"Gemini: Interaction {idx + 1}",
                "timestamp": timestamp,
                "tags": "gemini,chat",
            }

    except Exception as e:
        print(f"[ingestion.gemini] Error parsing {filepath}: {e}", file=sys.stderr)


def _extract_card_timestamp(card, filepath: Path) -> str:
    """
    Try to find a timestamp within a Gemini activity card.
    Falls back to file modification time.
    """
    try:
        from dateutil import parser as date_parser

        # Look for common date containers in Takeout HTML
        date_cells = card.find_all("div", class_="content-cell")
        for cell in date_cells:
            text = cell.get_text(strip=True)
            # dateutil.parser is very flexible with date formats
            try:
                dt = date_parser.parse(text, fuzzy=True)
                return dt.isoformat()
            except (ValueError, OverflowError):
                continue
    except ImportError:
        pass

    return _file_timestamp(filepath)


def _file_timestamp(filepath: Path) -> str:
    """Fallback: use file modification time."""
    mtime = filepath.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime).isoformat()
