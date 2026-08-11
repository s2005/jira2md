"""Raw response cache for jira2md.

Layout: ``<cache-dir>/<host>/<KEY>.json`` holds the raw issue payload
and ``<KEY>_meta.json`` holds fetch metadata (timestamp, ETag, request
parameters). Secrets never enter the cache: metadata is built from an
allowlist, never copied from request headers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger("jira2md")


def _host_dir(cache_dir: Path, host: str) -> Path:
    """Directory holding all cached entries for one Jira host."""
    return cache_dir / (host or "default")


def issue_cache_paths(cache_dir: Path, host: str, key: str) -> tuple[Path, Path]:
    """Return the (payload, metadata) file paths for one issue."""
    directory = _host_dir(cache_dir, host)
    return directory / f"{key}.json", directory / f"{key}_meta.json"


def write_issue_cache(
    cache_dir: Path,
    host: str,
    key: str,
    payload: Mapping[str, Any],
    *,
    meta: Mapping[str, Any],
) -> None:
    """Persist one issue payload plus sanitised metadata."""
    payload_path, meta_path = issue_cache_paths(cache_dir, host, key)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    meta_path.write_text(
        json.dumps(sanitize_meta(meta), indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    logger.debug("cached issue %s at %s", key, payload_path)


def read_issue_cache(
    cache_dir: Path, host: str, key: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Load a cached issue; returns (payload, meta) or None when absent."""
    payload_path, meta_path = issue_cache_paths(cache_dir, host, key)
    if not payload_path.is_file():
        return None
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Unreadable cache entry %s: %s", payload_path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Unexpected cache payload shape in %s", payload_path)
        return None
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable cache metadata %s: %s", meta_path, exc)
            loaded = None
        if isinstance(loaded, dict):
            meta = loaded
    return payload, meta


_META_ALLOWED = ("fetched_at", "etag", "fields", "endpoint")


def sanitize_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce metadata to the allowlisted, secret-free keys."""
    clean: dict[str, Any] = {}
    for name in _META_ALLOWED:
        if meta.get(name) is not None:
            clean[name] = meta[name]
    return clean
