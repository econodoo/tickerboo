"""
Asset versioning for TickerBoo static files.

Usage in templates / responses:
    from tickerboo.assets import asset_url
    url = asset_url("sidebar.js")  # → "/static/sidebar.js?v=a3f8c2"

Hash is computed once at startup from file contents (SHA-1 truncated to 8 chars).
Unknown files (don't exist yet) get version=0 as a safe fallback.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_cache: dict[str, str] = {}


def _hash_file(path: Path) -> str:
    """SHA-1 of file contents, first 8 hex chars."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:8]
    except OSError:
        return "00000000"


def warm_asset_cache() -> None:
    """Call once at startup to hash all static files."""
    _cache.clear()
    if not _STATIC_DIR.exists():
        return
    for p in _STATIC_DIR.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(_STATIC_DIR))
            _cache[rel] = _hash_file(p)
            log.debug("asset hash: %s → %s", rel, _cache[rel])
    log.info("Asset cache warmed: %d file(s)", len(_cache))


def asset_url(filename: str, static_prefix: str = "/static") -> str:
    """Return versioned URL for a static asset.

    Example:
        asset_url("sidebar.js")  →  "/static/sidebar.js?v=a3f8c2"
    """
    v = _cache.get(filename, "0")
    return f"{static_prefix}/{filename}?v={v}"
