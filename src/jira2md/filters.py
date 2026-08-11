"""Jinja filters and tests for jira2md templates.

Every filter is a pure function operating on model values so that it
can be unit-tested in isolation and reused outside Jinja. Rich-text
conversion (``wiki`` / ``adf``) happens here at render time, keeping
the data model transport-agnostic.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import yaml
from jinja2 import pass_context

from jira2md.markup.wiki import wiki_to_md
from jira2md.model import Issue, User

if TYPE_CHECKING:
    from jinja2.runtime import Context

_DONE_STATUSES = frozenset({"done", "closed", "resolved", "complete"})


@pass_context
def wiki_filter(context: Context, value: Any) -> str:
    """Convert Jira wiki markup to Markdown.

    When the render context carries the current issue, ``!name!`` image
    references are rewritten to that issue's attachment targets (the
    downloaded asset path, or the Jira content URL under --no-assets).
    """
    if not value:
        return ""
    issue = context.get("issue")
    asset_urls: dict[str, str] | None = None
    if issue is not None and getattr(issue, "attachments", None):
        asset_urls = {
            attachment.filename: attachment.path or attachment.content_url
            for attachment in issue.attachments
            if attachment.filename
        }
    return wiki_to_md(str(value), asset_urls=asset_urls)


def adf_filter(value: Any) -> str:
    """Convert an ADF payload to Markdown."""
    from jira2md.markup.adf import adf_to_md

    return adf_to_md(value)


def yaml_filter(value: Any) -> str:
    """Serialise a mapping to a YAML block without document markers."""
    if value is None:
        return ""
    return yaml.safe_dump(
        value,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def slug_filter(value: Any) -> str:
    """Produce a filename-safe slug from arbitrary text."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def isodate_filter(value: Any) -> str:
    """Render a datetime (or Jira timestamp string) as ISO-8601."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    from jira2md.model import _parse_datetime

    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else str(value)


def reldate_filter(value: Any, *, now: datetime | None = None) -> str:
    """Render a datetime as a human relative string ("3 days ago")."""
    if not value:
        return ""
    if isinstance(value, str):
        from jira2md.model import _parse_datetime

        value = _parse_datetime(value)
    if not isinstance(value, datetime):
        return ""
    reference = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = reference - value
    seconds = int(delta.total_seconds())
    future = seconds < 0
    seconds = abs(seconds)

    def _label(amount: int, unit: str) -> str:
        plural = unit if amount == 1 else f"{unit}s"
        return f"in {amount} {plural}" if future else f"{amount} {plural} ago"

    if seconds < 60:
        return "just now" if not future else "in moments"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return _label(minutes, "minute")
    hours, _ = divmod(minutes, 60)
    if hours < 24:
        return _label(hours, "hour")
    days, _ = divmod(hours, 24)
    if days < 30:
        return _label(days, "day")
    months = days // 30
    if months < 12:
        return _label(months, "month")
    return _label(months // 12, "year")


def indent_md_filter(value: Any, width: int = 2) -> str:
    """Indent each line without breaking fenced code blocks."""
    text = str(value or "")
    pad = " " * int(width)
    in_fence = False
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            out.append(line)
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            out.append(line)
            continue
        out.append(f"{pad}{line}")
    return "\n".join(out)


def heading_filter(value: Any, level: int = 1) -> str:
    """Normalise heading markers on each heading line to ``level``."""
    text = str(value or "")
    prefix = "#" * max(1, min(int(level), 6))
    out: list[str] = []
    for line in text.split("\n"):
        match = re.match(r"^(#{1,6})\s*(.*)$", line)
        if match:
            out.append(f"{prefix} {match.group(2)}")
        else:
            out.append(line)
    return "\n".join(out)


def jirauser_filter(value: Any) -> str:
    """Return a display name, falling back to the account identifier."""
    if value is None:
        return ""
    if isinstance(value, User):
        return value.display_name or value.account_id or ""
    if isinstance(value, Mapping):
        name = value.get("displayName") or value.get("name")
        if name:
            return str(name)
        return str(value.get("accountId") or value.get("key") or "")
    return str(value)


def is_epic(issue: Issue) -> bool:
    """Jinja test: the issue is an Epic."""
    return issue.issue_type.lower() == "epic"


def is_done(issue: Issue) -> bool:
    """Jinja test: the issue is resolved or in a done-like status."""
    if issue.resolution:
        return True
    return issue.status.lower() in _DONE_STATUSES


def has_attachments(issue: Issue) -> bool:
    """Jinja test: the issue carries at least one attachment."""
    return bool(issue.attachments)


FILTERS: dict[str, Any] = {
    "wiki": wiki_filter,
    "adf": adf_filter,
    "yaml": yaml_filter,
    "slug": slug_filter,
    "isodate": isodate_filter,
    "reldate": reldate_filter,
    "indent_md": indent_md_filter,
    "heading": heading_filter,
    "jirauser": jirauser_filter,
}

TESTS: dict[str, Any] = {
    "is_epic": is_epic,
    "is_done": is_done,
    "has_attachments": has_attachments,
}
