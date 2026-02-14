"""Extract movie code and subtitle language from a filename."""

import re
from pathlib import Path


# Movie code pattern: 2-6 uppercase letters, dash, 1-5 digits
MOVIE_CODE_RE = re.compile(r'([A-Za-z]{2,6})-(\d{1,5})')

# Subtitle keyword mapping (checked in order, first match wins)
SUBTITLE_KEYWORDS = [
    (re.compile(r'english\s*sub(?:bed|s|title[ds]?)?', re.IGNORECASE), 'English Sub'),
    (re.compile(r'\beng\b', re.IGNORECASE), 'English Sub'),
    (re.compile(r'chinese\s*sub(?:bed|s|title[ds]?)?', re.IGNORECASE), 'Chinese Sub'),
    (re.compile(r'\bchi\b', re.IGNORECASE), 'Chinese Sub'),
]


def extract_movie_code(filename: str) -> str | None:
    """Extract a movie code like 'SONE-760' from a filename.

    Returns the code in uppercase or None if not found.
    """
    stem = Path(filename).stem
    match = MOVIE_CODE_RE.search(stem)
    if match:
        return f'{match.group(1).upper()}-{match.group(2)}'
    return None


def detect_subtitle(filename: str) -> str:
    """Detect subtitle language from filename keywords.

    Returns 'English Sub', 'Chinese Sub', or 'No Sub'.
    """
    stem = Path(filename).stem
    for pattern, label in SUBTITLE_KEYWORDS:
        if pattern.search(stem):
            return label
    return 'No Sub'
