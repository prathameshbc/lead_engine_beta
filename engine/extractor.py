"""Text extraction from raw HTML using trafilatura."""
from __future__ import annotations
from typing import Optional
import trafilatura


def extract_text(html: str) -> Optional[str]:
    """
    Extract main-content text from an HTML page.
    Returns None if the result is too short to be useful.
    """
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        deduplicate=True,
    )
    return text if text and len(text.strip()) > 80 else None
