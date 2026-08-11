"""Tests for the jira2md normalised model."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jira2md.model import (
    Attachment,
    Comment,
    Issue,
    IssueLink,
    IssueRef,
    User,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def issue_payload() -> dict:
    with (FIXTURES / "issue_full.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class TestFromApi:
    def test_scalar_fields(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload, base_url="https://example.atlassian.net")
        assert issue.key == "ABC-123"
        assert issue.summary == "Sample issue for tests"
        assert issue.description == "h1. Heading\n\nSome *bold* text."
        assert issue.issue_type == "Story"
        assert issue.status == "In Progress"
        assert issue.priority == "High"
        assert issue.resolution is None

    def test_users(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.assignee is not None
        assert issue.assignee.display_name == "Alice Example"
        assert issue.assignee.account_id == "abc-account-1"
        assert issue.reporter is not None
        assert issue.reporter.display_name == "Bob Example"

    def test_timestamps_are_tz_aware(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.created == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        assert issue.updated == datetime(2024, 2, 20, 14, 45, tzinfo=timezone.utc)
        assert issue.resolved is None

    def test_collection_fields(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.labels == ("backend", "urgent")
        assert issue.components == ("API", "Auth")
        assert issue.fix_versions == ("1.0", "1.1")

    def test_parent_and_subtasks(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.parent is not None
        assert issue.parent.key == "ABC-100"
        assert len(issue.subtasks) == 1
        assert issue.subtasks[0].key == "ABC-124"
        assert issue.subtasks[0].status == "Done"

    def test_links(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert len(issue.links) == 2
        outward = issue.links[0]
        assert outward.direction == "outward"
        assert outward.link_type == "blocks"
        assert outward.target.key == "ABC-125"
        inward = issue.links[1]
        assert inward.direction == "inward"
        assert inward.link_type == "is duplicated by"
        assert inward.target.key == "ABC-126"

    def test_attachments(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert len(issue.attachments) == 1
        attachment = issue.attachments[0]
        assert attachment.filename == "diagram.png"
        assert attachment.size == 12345
        assert attachment.mime_type == "image/png"
        assert "diagram.png" in attachment.content_url

    def test_comments_sorted_chronologically(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert len(issue.comments) == 2
        assert issue.comments[0].id == "30001"
        assert issue.comments[1].id == "30002"

    def test_custom_fields_keyed_by_id_without_map(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.custom["customfield_10014"] == "EPIC-1"
        assert issue.custom["customfield_10016"] == 8.0

    def test_custom_fields_keyed_by_name_with_map(self, issue_payload: dict) -> None:
        issue = Issue.from_api(
            issue_payload,
            field_map={
                "customfield_10014": "Epic Link",
                "customfield_10016": "Story Points",
            },
        )
        assert issue.custom["Epic Link"] == "EPIC-1"
        assert issue.custom["Story Points"] == 8.0
        assert "customfield_10014" not in issue.custom

    def test_browse_url(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload, base_url="https://example.atlassian.net/")
        assert issue.url == "https://example.atlassian.net/browse/ABC-123"

    def test_raw_payload_preserved(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload)
        assert issue.raw["id"] == "10000"

    def test_minimal_payload(self) -> None:
        issue = Issue.from_api({"key": "X-1", "fields": {}})
        assert issue.key == "X-1"
        assert issue.summary == ""
        assert issue.description is None
        assert issue.assignee is None
        assert issue.labels == ()
        assert issue.comments == ()
        assert issue.url == ""

    def test_empty_fields_payload(self) -> None:
        issue = Issue.from_api({"key": "X-2"})
        assert issue.key == "X-2"


class TestFrontmatter:
    def test_frontmatter_contents(self, issue_payload: dict) -> None:
        issue = Issue.from_api(issue_payload, base_url="https://example.atlassian.net")
        frontmatter = issue.frontmatter
        assert frontmatter["key"] == "ABC-123"
        assert frontmatter["summary"] == "Sample issue for tests"
        assert frontmatter["type"] == "Story"
        assert frontmatter["status"] == "In Progress"
        assert frontmatter["assignee"] == "Alice Example"
        assert frontmatter["resolution"] is None
        assert frontmatter["labels"] == ["backend", "urgent"]
        assert frontmatter["fix_versions"] == ["1.0", "1.1"]
        assert frontmatter["created"].startswith("2024-01-15T10:30:00")


class TestSupportingModels:
    def test_user_from_empty_payload(self) -> None:
        assert User.from_api(None) is None
        assert User.from_api({}) is None

    def test_user_server_style_payload(self) -> None:
        user = User.from_api({"name": "jsmith", "displayName": "John Smith"})
        assert user is not None
        assert user.display_name == "John Smith"
        assert user.account_id == "jsmith"

    def test_issue_ref_from_empty_payload(self) -> None:
        assert IssueRef.from_api(None) is None

    def test_issue_link_without_target(self) -> None:
        assert IssueLink.from_api({"type": {"inward": "x"}}) is None

    def test_attachment_bad_size(self) -> None:
        attachment = Attachment.from_api({"filename": "a.txt", "size": "not-a-number"})
        assert attachment is not None
        assert attachment.size == 0

    def test_comment_from_empty_payload(self) -> None:
        assert Comment.from_api(None) is None

    def test_parse_datetime_invalid(self) -> None:
        issue = Issue.from_api({"key": "X-3", "fields": {"created": "not-a-date"}})
        assert issue.created.tzinfo is not None
