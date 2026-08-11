"""Property tests: rendered Markdown re-parses cleanly.

Every shipped template's output is fed back through ``markdown-it-py``
(dev-only dependency): parsing must not raise, and fenced code blocks
must be balanced (every fence opened is closed).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from markdown_it import MarkdownIt

from jira2md.model import Issue
from jira2md.render import render

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_issue_payload() -> dict[str, Any]:
    with (FIXTURES / "issue_full.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def make_issue(description: str | None = None) -> Issue:
    payload = load_issue_payload()
    if description is not None:
        payload["fields"]["description"] = description
    return Issue.from_api(payload, base_url="https://example.atlassian.net")


def base_context(issue: Issue) -> dict[str, Any]:
    return {
        "issue": issue,
        "raw": issue.raw,
        "issues": [issue],
        "base_url": "https://example.atlassian.net",
        "now": NOW,
        "fields": {},
        "config": {"frontmatter": True, "assets_dir": "assets"},
    }


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML front matter block before re-parsing."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + len("\n---\n") :]


def assert_reparses(content: str) -> None:
    body = strip_frontmatter(content)
    parser = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    tokens = parser.parse(body)
    assert isinstance(tokens, list)
    # Balanced fences: every opening ``` has a matching close.
    assert body.count("```") % 2 == 0


TEMPLATES = ["issue.md.j2", "index.md.j2", "single.md.j2", "release-notes.md.j2"]


class TestRenderedOutputReparses:
    @pytest.mark.parametrize("template", TEMPLATES)
    def test_shipped_templates_reparse(self, template: str) -> None:
        issue = make_issue()
        content = render([issue], template, base_context(issue))
        assert_reparses(content)

    def test_rich_description_reparse(self) -> None:
        issue = make_issue(
            description=(
                "h1. Title\n\n"
                "*bold* _italic_ -strike- {{mono}}\n\n"
                "{code:python}\ndef f():\n    return '*not markup*'\n{code}\n\n"
                "|a|b|\n|1|2|\n\n"
                "!diagram.png!"
            )
        )
        content = render([issue], "issue.md.j2", base_context(issue))
        assert_reparses(content)
        assert "```python" in content
        assert "'*not markup*'" in content

    def test_code_block_inner_formatting_untouched(self) -> None:
        issue = make_issue(description="{code}\n*not bold* and !not-an-asset!\n{code}")
        content = render([issue], "issue.md.j2", base_context(issue))
        assert "*not bold* and !not-an-asset!" in content
        assert_reparses(content)
