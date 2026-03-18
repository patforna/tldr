"""Cache management for tldr — stores extracted content and summaries."""

import hashlib
import os
import platform
import re
from pathlib import Path


def _cache_dir() -> Path:
    """Return the platform-appropriate cache directory for tldr.

    - Linux: $XDG_CACHE_HOME/tldr (defaults to ~/.cache/tldr)
    - macOS: ~/Library/Caches/tldr
    """
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Caches" / "tldr"
    # Linux and other Unix-like systems follow XDG
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "tldr"
    return Path.home() / ".cache" / "tldr"


def _cache_key(source: str) -> str:
    """Generate a stable cache key from a source identifier.

    For URLs, the key is a SHA-256 hash of the URL.
    For local files, the key incorporates the absolute path and modification
    time so the cache auto-invalidates when the file changes.
    """
    if source.startswith(("http://", "https://")):
        identity = source
    else:
        path = Path(source).expanduser()
        try:
            mtime = path.stat().st_mtime
            identity = f"{path.resolve()}:{mtime}"
        except OSError:
            identity = source
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def _entry_dir(source: str) -> Path:
    """Return the cache directory for a specific source."""
    return _cache_dir() / _cache_key(source)


def get_content(source: str) -> str | None:
    """Return cached extracted content for *source*, or None on miss."""
    content_file = _entry_dir(source) / "content.txt"
    if content_file.is_file():
        return content_file.read_text()
    return None


def put_content(source: str, text: str) -> None:
    """Store extracted content for *source* in the cache."""
    entry = _entry_dir(source)
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "content.txt").write_text(text)



def _safe_model_name(model: str) -> str:
    """Sanitize model name for use in filenames (prevents path traversal)."""
    return re.sub(r"[^\w.-]", "_", model)


def get_summary(source: str, model: str) -> str | None:
    """Return cached summary for *source* + *model*, or None on miss."""
    summary_file = _entry_dir(source) / f"{_safe_model_name(model)}.summary.txt"
    if summary_file.is_file():
        return summary_file.read_text()
    return None


def put_summary(source: str, model: str, text: str) -> None:
    """Store a summary for *source* + *model* in the cache."""
    entry = _entry_dir(source)
    entry.mkdir(parents=True, exist_ok=True)
    (entry / f"{_safe_model_name(model)}.summary.txt").write_text(text)


def get_critique(source: str, model: str) -> str | None:
    """Return cached critique for *source* + *model*, or None on miss."""
    critique_file = _entry_dir(source) / f"{_safe_model_name(model)}.critique.txt"
    if critique_file.is_file():
        return critique_file.read_text()
    return None


def put_critique(source: str, model: str, text: str) -> None:
    """Store a critique for *source* + *model* in the cache."""
    entry = _entry_dir(source)
    entry.mkdir(parents=True, exist_ok=True)
    (entry / f"{_safe_model_name(model)}.critique.txt").write_text(text)
