"""Attachment handling for jira2md.

Downloads issue attachments with the client's auth headers into
``<out>/<assets-dir>/<KEY>/<filename>`` and rewrites ``!name!`` image
references to the local files. Name collisions within one issue get
``-1``, ``-2``, ... suffixes before the file extension.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from jira2md.model import Attachment, Issue

if TYPE_CHECKING:
    from jira2md.client import JiraClient

logger = logging.getLogger("jira2md")


def stored_filename(attachment: Attachment, used: dict[str, int]) -> str:
    """Assign a collision-free filename for one attachment.

    Args:
        attachment: Attachment whose filename may collide.
        used: Mutable count of names already taken in this issue.

    Returns:
        The stored filename (original or with a ``-N`` suffix).
    """
    name = Path(attachment.filename or "attachment").name or "attachment"
    count = used.get(name, 0)
    used[name] = count + 1
    if count == 0:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    candidate = f"{stem}-{count}.{extension}" if extension else f"{stem}-{count}"
    used[candidate] = used.get(candidate, 0) + 1
    return candidate


def asset_url_map(
    attachments: Sequence[Attachment], stored: Sequence[str]
) -> dict[str, str]:
    """Map bare attachment filenames to their local (or remote) targets."""
    mapping: dict[str, str] = {}
    for attachment, name in zip(attachments, stored, strict=False):
        if attachment.filename and attachment.filename not in mapping:
            mapping[attachment.filename] = name
    return mapping


def apply_attachment_paths(
    issues: Iterable[Issue],
    *,
    assets_dir: str,
    download_assets: bool,
) -> list[Issue]:
    """Set each attachment ``path`` to its render-time link target.

    With downloads enabled the path is the local file location relative
    to the output directory; with ``--no-assets`` it keeps the Jira
    ``content`` URL.
    """
    updated: list[Issue] = []
    for issue in issues:
        if not issue.attachments:
            updated.append(issue)
            continue
        used: dict[str, int] = {}
        attachments = []
        for attachment in issue.attachments:
            stored = stored_filename(attachment, used)
            if download_assets:
                path = f"{assets_dir}/{issue.key}/{stored}"
            else:
                path = attachment.content_url or stored
            attachments.append(dataclasses.replace(attachment, path=path))
        updated.append(dataclasses.replace(issue, attachments=tuple(attachments)))
    return updated


async def download_attachments(
    client: JiraClient,
    issue: Issue,
    out_dir: Path,
    *,
    assets_dir: str,
) -> int:
    """Download every attachment of one issue below the output dir.

    A download whose byte count disagrees with the size Jira reports is
    truncated or empty; it is logged and skipped rather than written, so
    a corrupt file never masquerades as a successful download.

    Args:
        client: Authenticated client used for the raw byte downloads.
        issue: Issue whose attachments carry resolved ``path`` values.
        out_dir: Directory that receives the rendered Markdown files.
        assets_dir: Attachment directory name relative to ``out_dir``.

    Returns:
        Number of files written.
    """
    written = 0
    for attachment in issue.attachments:
        if not attachment.content_url or not attachment.path:
            continue
        content = await client.download_content(attachment.content_url)
        if attachment.size and len(content) != attachment.size:
            logger.error(
                "Skipping %s of %s: downloaded %d bytes, Jira reports %d",
                attachment.filename,
                issue.key,
                len(content),
                attachment.size,
            )
            continue
        target = out_dir / Path(attachment.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written += 1
        logger.debug("downloaded %s -> %s", attachment.content_url, target)
    return written
