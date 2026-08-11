"""Unit tests for the jira2md Jinja filters and tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jira2md.filters import (
    adf_filter,
    has_attachments,
    heading_filter,
    indent_md_filter,
    is_done,
    is_epic,
    isodate_filter,
    jirauser_filter,
    reldate_filter,
    slug_filter,
    wiki_filter,
    yaml_filter,
)
from jira2md.model import Attachment, Issue, User

_NOW = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)


def _issue(**overrides: object) -> Issue:
    defaults = {
        "key": "ABC-1",
        "summary": "Summary",
        "description": None,
        "issue_type": "Story",
        "status": "In Progress",
        "priority": None,
        "resolution": None,
        "assignee": None,
        "reporter": None,
        "created": _NOW,
        "updated": _NOW,
        "resolved": None,
        "labels": (),
        "components": (),
        "fix_versions": (),
        "parent": None,
        "subtasks": (),
        "links": (),
        "attachments": (),
        "comments": (),
        "custom": {},
        "url": "",
        "raw": {},
    }
    defaults.update(overrides)
    return Issue(**defaults)  # type: ignore[arg-type]


class _FakeContext:
    """Minimal stand-in for jinja2.runtime.Context in direct calls."""

    def __init__(self, values: dict | None = None) -> None:
        self._values = values or {}

    def get(self, key: str) -> object:
        return self._values.get(key)


class TestWikiFilter:
    def test_converts_markup(self) -> None:
        assert wiki_filter(_FakeContext(), "h1. Title") == "# Title"

    def test_empty_value(self) -> None:
        assert wiki_filter(_FakeContext(), None) == ""

    def test_image_reference_rewritten_to_asset_path(self) -> None:
        attachment = Attachment(
            filename="diagram.png",
            content_url="https://jira.example.com/secure/attachment/1/diagram.png",
            path="assets/ABC-1/diagram.png",
        )
        issue = _issue(attachments=(attachment,))
        context = _FakeContext({"issue": issue})
        rendered = wiki_filter(context, "see !diagram.png!")
        assert "![](assets/ABC-1/diagram.png)" in rendered

    def test_image_reference_keeps_content_url_without_assets(self) -> None:
        attachment = Attachment(
            filename="diagram.png",
            content_url="https://jira.example.com/secure/attachment/1/diagram.png",
            path="https://jira.example.com/secure/attachment/1/diagram.png",
        )
        issue = _issue(attachments=(attachment,))
        context = _FakeContext({"issue": issue})
        rendered = wiki_filter(context, "!diagram.png!")
        assert "secure/attachment/1/diagram.png" in rendered


class TestAdfFilter:
    def test_empty_doc_renders_empty(self) -> None:
        assert adf_filter({"type": "doc"}) == ""

    def test_paragraph_renders_through_filter(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "hi"}],
                }
            ],
        }
        assert adf_filter(doc) == "hi"


class TestYamlFilter:
    def test_mapping_round_trip(self) -> None:
        result = yaml_filter({"a": 1, "b": "two"})
        assert result == "a: 1\nb: two\n"

    def test_none_renders_empty(self) -> None:
        assert yaml_filter(None) == ""


class TestSlugFilter:
    def test_basic(self) -> None:
        assert slug_filter("Hello, World!") == "hello-world"

    def test_unicode_is_transliterated(self) -> None:
        assert slug_filter("Caf\u00e9 \u2014 R\u00e9sum\u00e9") == "cafe-resume"

    def test_runs_collapse_and_strip(self) -> None:
        assert slug_filter("  --Multiple   spaces--  ") == "multiple-spaces"


class TestIsodateFilter:
    def test_datetime_passthrough(self) -> None:
        value = datetime(2024, 1, 2, 3, 4, tzinfo=timezone.utc)
        assert isodate_filter(value) == "2024-01-02T03:04:00+00:00"

    def test_jira_string_parsed(self) -> None:
        assert isodate_filter("2024-01-02T03:04:05.000+0000") == (
            "2024-01-02T03:04:05+00:00"
        )

    def test_missing_value(self) -> None:
        assert isodate_filter(None) == ""


class TestReldateFilter:
    def test_days_ago(self) -> None:
        value = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        assert reldate_filter(value, now=_NOW) == "3 days ago"

    def test_hours_ago(self) -> None:
        value = datetime(2026, 1, 8, 9, 0, tzinfo=timezone.utc)
        assert reldate_filter(value, now=_NOW) == "3 hours ago"

    def test_future(self) -> None:
        value = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
        assert reldate_filter(value, now=_NOW) == "in 2 days"

    def test_just_now(self) -> None:
        assert reldate_filter(_NOW, now=_NOW) == "just now"


class TestIndentMdFilter:
    def test_indents_plain_lines(self) -> None:
        assert indent_md_filter("a\nb", 2) == "  a\n  b"

    def test_fenced_code_not_indented(self) -> None:
        text = "intro\n```\ncode\n```\noutro"
        result = indent_md_filter(text, 2)
        assert result == "  intro\n```\ncode\n```\n  outro"

    def test_blank_lines_untouched(self) -> None:
        assert indent_md_filter("a\n\nb", 4) == "    a\n\n    b"


class TestHeadingFilter:
    def test_shifts_existing_levels(self) -> None:
        assert heading_filter("## Deep\n#### Deeper", 1) == "# Deep\n# Deeper"

    def test_non_heading_lines_kept(self) -> None:
        assert heading_filter("plain\n## H", 3) == "plain\n### H"

    def test_level_clamped(self) -> None:
        assert heading_filter("text", 9) == "text"


class TestJirauserFilter:
    def test_user_object(self) -> None:
        user = User(display_name="Alice", account_id="a1")
        assert jirauser_filter(user) == "Alice"

    def test_user_without_display_name_falls_back(self) -> None:
        user = User(display_name="", account_id="a1")
        assert jirauser_filter(user) == "a1"

    def test_dict_payload(self) -> None:
        assert jirauser_filter({"displayName": "Bob"}) == "Bob"
        assert jirauser_filter({"accountId": "x9"}) == "x9"

    def test_none_and_string(self) -> None:
        assert jirauser_filter(None) == ""
        assert jirauser_filter("plain") == "plain"


class TestJinjaTests:
    def test_is_epic(self) -> None:
        assert is_epic(_issue(issue_type="Epic"))
        assert not is_epic(_issue(issue_type="Story"))

    def test_is_done_via_resolution(self) -> None:
        assert is_done(_issue(resolution="Done"))

    def test_is_done_via_status(self) -> None:
        assert is_done(_issue(status="Closed"))
        assert not is_done(_issue(status="In Progress"))

    def test_has_attachments(self) -> None:
        attachment = Attachment(filename="a.png")
        assert has_attachments(_issue(attachments=(attachment,)))
        assert not has_attachments(_issue())


class TestFilterRegistration:
    def test_filters_registered_on_environment(self) -> None:
        from jira2md.render import build_environment

        env = build_environment()
        for name in (
            "wiki",
            "adf",
            "yaml",
            "slug",
            "isodate",
            "reldate",
            "indent_md",
            "heading",
            "jirauser",
        ):
            assert name in env.filters
        for name in ("is_epic", "is_done", "has_attachments"):
            assert name in env.tests


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Fix the login", "fix-the-login"), ("", "")],
)
def test_slug_parametrized(value: str, expected: str) -> None:
    assert slug_filter(value) == expected
