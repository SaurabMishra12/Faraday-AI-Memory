"""
ingestion.image — Extract text from images via OCR.

Uses Pillow + pytesseract.  Gracefully degrades if Tesseract
is not installed — warns ONCE and skips all images silently.
"""

import datetime
import sys
from pathlib import Path
from typing import Dict, Generator

# Module-level availability check — run once, not per-file
_ocr_available = None
_ocr_warned = False


def _check_ocr():
    """Check OCR availability once at module level."""
    global _ocr_available, _ocr_warned

    if _ocr_available is not None:
        return _ocr_available

    try:
        from config import OCR_ENABLED
        if not OCR_ENABLED:
            _ocr_available = False
            return False
    except ImportError:
        pass

    try:
        from PIL import Image  # noqa: F401
        import pytesseract  # noqa: F401
        _ocr_available = True
    except ImportError:
        _ocr_available = False
        if not _ocr_warned:
            print(
                "[ingestion.image] OCR unavailable (Pillow/pytesseract not installed). "
                "Skipping all images.",
                file=sys.stderr,
            )
            _ocr_warned = True

    return _ocr_available


def parse_image(filepath: Path) -> Generator[Dict, None, None]:
    """
    Run OCR on an image file and yield extracted text as a document.
    Skips silently if OCR dependencies are missing (logs once).
    """
    if not _check_ocr():
        return

    from PIL import Image
    import pytesseract

    # Configure tesseract path if provided
    try:
        from config import TESSERACT_CMD
        if TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    except ImportError:
        pass

    try:
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)

        if not text or len(text.strip()) < 20:
            return

        mtime = filepath.stat().st_mtime
        timestamp = datetime.datetime.fromtimestamp(mtime).isoformat()

        yield {
            "text": text.strip(),
            "source": f"OCR: {filepath.name}",
            "timestamp": timestamp,
            "tags": "image,ocr",
        }

    except Exception as e:
        error_name = type(e).__name__
        if "Tesseract" in error_name:
            global _ocr_available, _ocr_warned
            _ocr_available = False
            if not _ocr_warned:
                print(
                    f"[ingestion.image] Tesseract not found. "
                    f"Install it or set TESSERACT_CMD in config.py.",
                    file=sys.stderr,
                )
                _ocr_warned = True
        else:
            print(
                f"[ingestion.image] Error processing {filepath}: {e}",
                file=sys.stderr,
            )
