"""Normalised data model for jira2md.

Frozen dataclasses hold Jira REST API v2 payloads in a stable shape.
Rich text stays raw on the model; conversion to Markdown happens at
render time so templates can opt out of conversion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a Jira timestamp string into a timezone-aware datetime.

    Args:
        value: Raw timestamp value from the API payload.

    Returns:
        Timezone-aware datetime, or None when the value is missing
        or cannot be parsed.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = date_parser.isoparse(value)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _str_tuple(values: Any) -> tuple[str, ...]:
    """Convert a raw list payload into a tuple of strings."""
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if item is not None)


def _name_tuple(values: Any, key: str = "name") -> tuple[str, ...]:
    """Extract the ``name`` attribute of each dict in a raw list."""
    if not isinstance(values, list):
        return ()
    names: list[str] = []
    for item in values:
        if isinstance(item, dict) and item.get(key):
            names.append(str(item[key]))
    return tuple(names)


@dataclass(frozen=True)
class User:
    """A Jira user reference."""

    display_name: str
    account_id: str | None = None
    email: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> User | None:
        """Build a User from a raw API user payload.

        Args:
            payload: Raw user dict from the REST API.

        Returns:
            A User instance, or None for a missing/empty payload.
        """
        if not payload:
            return None
        display_name = payload.get("displayName") or payload.get("name") or ""
        account_id = (
            payload.get("accountId") or payload.get("key") or payload.get("name")
        )
        email = payload.get("emailAddress")
        return cls(
            display_name=str(display_name),
            account_id=str(account_id) if account_id else None,
            email=str(email) if email else None,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class IssueRef:
    """A lightweight reference to another issue."""

    key: str
    summary: str = ""
    status: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> IssueRef | None:
        """Build an IssueRef from a raw API issue payload.

        Args:
            payload: Raw issue dict from the REST API.

        Returns:
            An IssueRef instance, or None for a missing/empty payload.
        """
        if not payload:
            return None
        fields = payload.get("fields") or {}
        status = ""
        status_payload = fields.get("status") if isinstance(fields, dict) else None
        if isinstance(status_payload, dict):
            status = str(status_payload.get("name") or "")
        summary = fields.get("summary") if isinstance(fields, dict) else None
        return cls(
            key=str(payload.get("key") or ""),
            summary=str(summary) if summary else "",
            status=status,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class IssueLink:
    """A link between two issues."""

    link_type: str
    direction: str
    target: IssueRef
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> IssueLink | None:
        """Build an IssueLink from a raw API issuelink payload.

        Args:
            payload: Raw issuelink dict from the REST API.

        Returns:
            An IssueLink instance, or None for a missing/empty payload.
        """
        if not payload:
            return None
        link_type_payload = payload.get("type") or {}
        if payload.get("outwardIssue"):
            direction = "outward"
            target_payload = payload.get("outwardIssue")
            type_name = link_type_payload.get("outward", "")
        else:
            direction = "inward"
            target_payload = payload.get("inwardIssue")
            type_name = link_type_payload.get("inward", "")
        target = IssueRef.from_api(target_payload)
        if target is None:
            return None
        return cls(
            link_type=str(type_name),
            direction=direction,
            target=target,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class Attachment:
    """An issue attachment."""

    filename: str
    size: int = 0
    mime_type: str = ""
    content_url: str = ""
    author: User | None = None
    created: datetime | None = None
    path: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> Attachment | None:
        """Build an Attachment from a raw API attachment payload.

        Args:
            payload: Raw attachment dict from the REST API.

        Returns:
            An Attachment instance, or None for a missing/empty payload.
        """
        if not payload:
            return None
        size_payload = payload.get("size") or 0
        try:
            size = int(size_payload)
        except (TypeError, ValueError):
            size = 0
        filename = str(payload.get("filename") or "")
        return cls(
            filename=filename,
            size=size,
            mime_type=str(payload.get("mimeType") or ""),
            content_url=str(payload.get("content") or ""),
            author=User.from_api(payload.get("author")),
            created=_parse_datetime(payload.get("created")),
            path=filename,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class Comment:
    """An issue comment."""

    id: str
    body: str
    author: User | None = None
    created: datetime | None = None
    updated: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> Comment | None:
        """Build a Comment from a raw API comment payload.

        Args:
            payload: Raw comment dict from the REST API.

        Returns:
            A Comment instance, or None for a missing/empty payload.
        """
        if not payload:
            return None
        return cls(
            id=str(payload.get("id") or ""),
            body=str(payload.get("body") or ""),
            author=User.from_api(payload.get("author")),
            created=_parse_datetime(payload.get("created")),
            updated=_parse_datetime(payload.get("updated")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class Issue:
    """Normalised Jira issue."""

    key: str
    summary: str
    description: str | None
    issue_type: str
    status: str
    priority: str | None
    resolution: str | None
    assignee: User | None
    reporter: User | None
    created: datetime
    updated: datetime
    resolved: datetime | None
    labels: tuple[str, ...]
    components: tuple[str, ...]
    fix_versions: tuple[str, ...]
    parent: IssueRef | None
    subtasks: tuple[IssueRef, ...]
    links: tuple[IssueLink, ...]
    attachments: tuple[Attachment, ...]
    comments: tuple[Comment, ...]
    custom: Mapping[str, Any]
    url: str
    raw: Mapping[str, Any]

    @property
    def frontmatter(self) -> dict[str, Any]:
        """YAML front matter payload for rendered documents."""
        return {
            "key": self.key,
            "summary": self.summary,
            "type": self.issue_type,
            "status": self.status,
            "priority": self.priority,
            "resolution": self.resolution,
            "assignee": self.assignee.display_name if self.assignee else None,
            "reporter": self.reporter.display_name if self.reporter else None,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "resolved": self.resolved.isoformat() if self.resolved else None,
            "labels": list(self.labels),
            "components": list(self.components),
            "fix_versions": list(self.fix_versions),
            "url": self.url,
        }

    @classmethod
    def from_api(
        cls,
        payload: Mapping[str, Any],
        *,
        field_map: Mapping[str, str] | None = None,
        base_url: str = "",
    ) -> Issue:
        """Normalise a raw REST API v2 issue payload.

        Args:
            payload: Full issue payload (``key`` + ``fields``).
            field_map: Optional ``customfield_id`` to human name map.
            base_url: Jira base URL used to build the browse link.

        Returns:
            A normalised Issue instance.
        """
        key = str(payload.get("key") or "")
        fields = payload.get("fields") or {}
        names = field_map or {}

        def _name(field_id: str) -> str:
            value = fields.get(field_id)
            if isinstance(value, dict):
                return str(value.get("name") or "")
            return ""

        def _text(field_id: str) -> str | None:
            value = fields.get(field_id)
            return str(value) if value else None

        comments_payload = fields.get("comment") or {}
        comments_raw = comments_payload.get("comments") or []
        comments = tuple(
            sorted(
                (
                    comment
                    for comment in (Comment.from_api(item) for item in comments_raw)
                    if comment is not None
                ),
                key=lambda comment: comment.created or _EPOCH,
            )
        )

        subtasks_raw = fields.get("subtasks") or []
        links_raw = fields.get("issuelinks") or []
        attachments_raw = fields.get("attachment") or []

        custom: dict[str, Any] = {}
        for field_id, value in fields.items():
            if field_id.startswith("customfield_"):
                custom[names.get(field_id, field_id)] = value

        url = f"{base_url.rstrip('/')}/browse/{key}" if base_url else ""

        return cls(
            key=key,
            summary=str(fields.get("summary") or ""),
            description=_text("description"),
            issue_type=_name("issuetype"),
            status=_name("status"),
            priority=_name("priority") or None,
            resolution=_name("resolution") or None,
            assignee=User.from_api(fields.get("assignee")),
            reporter=User.from_api(fields.get("reporter")),
            created=_parse_datetime(fields.get("created")) or _EPOCH,
            updated=_parse_datetime(fields.get("updated")) or _EPOCH,
            resolved=_parse_datetime(fields.get("resolutiondate")),
            labels=_str_tuple(fields.get("labels")),
            components=_name_tuple(fields.get("components")),
            fix_versions=_name_tuple(fields.get("fixVersions")),
            parent=IssueRef.from_api(fields.get("parent")),
            subtasks=tuple(
                ref
                for ref in (IssueRef.from_api(item) for item in subtasks_raw)
                if ref is not None
            ),
            links=tuple(
                link
                for link in (IssueLink.from_api(item) for item in links_raw)
                if link is not None
            ),
            attachments=tuple(
                attachment
                for attachment in (
                    Attachment.from_api(item) for item in attachments_raw
                )
                if attachment is not None
            ),
            comments=comments,
            custom=custom,
            url=url,
            raw=dict(payload),
        )
