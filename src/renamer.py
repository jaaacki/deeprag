"""Build new filenames, sanitize, and move files to destination."""

import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Characters invalid in filenames across common filesystems
INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Max filename length (conservative for most filesystems)
MAX_FILENAME_LEN = 200


def sanitize_filename(name: str) -> str:
    """Remove or replace characters invalid in filenames."""
    sanitized = INVALID_CHARS_RE.sub('', name)
    # Collapse multiple spaces/dots
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    sanitized = re.sub(r'\.{2,}', '.', sanitized)
    return sanitized


def build_filename(
    actress: str,
    subtitle: str,
    movie_code: str,
    title: str,
    extension: str,
) -> str:
    """Build filename: '{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}'.

    Truncates title if the full filename would exceed filesystem limits.
    """
    ext = extension if extension.startswith('.') else f'.{extension}'

    prefix = f'{actress} - [{subtitle}] {movie_code} '
    # Leave room for prefix + ext + safety margin
    max_title_len = MAX_FILENAME_LEN - len(prefix) - len(ext)

    if max_title_len < 10:
        # Extremely long prefix; use code-only fallback
        truncated_title = ''
    elif len(title) > max_title_len:
        truncated_title = title[:max_title_len].rstrip()
    else:
        truncated_title = title

    raw = f'{prefix}{truncated_title}{ext}'.strip()
    return sanitize_filename(raw)


def find_matching_folder(destination_dir: str, actress: str) -> str:
    """Find an existing actress folder via case-insensitive match.

    Returns the existing folder name if found, otherwise returns
    the properly-cased actress name for a new folder.
    """
    dest = Path(destination_dir)
    if not dest.exists():
        return actress

    normalized = _normalize_name(actress)
    for folder in dest.iterdir():
        if folder.is_dir() and _normalize_name(folder.name) == normalized:
            return folder.name

    return actress


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip common variations."""
    n = name.lower().strip()
    # Remove double letters at word boundaries that vary (e.g., "ou" vs "o")
    # Simple approach: just compare lowercase stripped
    n = re.sub(r'\s+', ' ', n)
    return n


def move_file(
    source_path: str,
    destination_dir: str,
    actress: str,
    new_filename: str,
) -> str:
    """Move a file to the actress subfolder in destination_dir.

    Creates the actress folder if it doesn't exist.
    Returns the new file path.
    """
    folder_name = find_matching_folder(destination_dir, actress)
    target_dir = Path(destination_dir) / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / new_filename

    # Handle name collision
    if target_path.exists():
        stem = target_path.stem
        ext = target_path.suffix
        counter = 1
        while target_path.exists():
            target_path = target_dir / f'{stem} ({counter}){ext}'
            counter += 1

    logger.info('Moving %s -> %s', source_path, target_path)
    shutil.move(source_path, str(target_path))
    return str(target_path)
