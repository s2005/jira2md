"""Tests for the jira2md Jinja renderer and shipped templates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from jira2md.cli import EXIT_OK, EXIT_TEMPLATE, run
from jira2md.client import HttpxJiraClient
from jira2md.config import Credentials
from jira2md.model import Issue
from jira2md.render import build_environment, render

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_issue_payload() -> dict[str, Any]:
    with (FIXTURES / "issue_full.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def make_issue() -> Issue:
    return Issue.from_api(
        load_issue_payload(), base_url="https://example.atlassian.net"
    )


def base_context(issue: Issue, *, frontmatter: bool = True) -> dict[str, Any]:
    return {
        "issue": issue,
        "raw": issue.raw,
        "base_url": "https://example.atlassian.net",
        "now": NOW,
        "fields": {},
        "config": {"frontmatter": frontmatter, "assets_dir": "assets"},
    }


class TestGoldenTemplates:
    def test_issue_template_matches_golden(self) -> None:
        issue = make_issue()
        result = render([issue], "issue.md.j2", base_context(issue))
        expected = (GOLDEN / "issue.md").read_text(encoding="utf-8")
        assert result == expected

    def test_issue_no_frontmatter_matches_golden(self) -> None:
        issue = make_issue()
        result = render([issue], "issue.md.j2", base_context(issue, frontmatter=False))
        expected = (GOLDEN / "issue-no-frontmatter.md").read_text(encoding="utf-8")
        assert result == expected

    def test_index_template_matches_golden(self) -> None:
        issue = make_issue()
        result = render([issue], "index.md.j2", base_context(issue))
        expected = (GOLDEN / "index.md").read_text(encoding="utf-8")
        assert result == expected

    def test_single_template_matches_golden(self) -> None:
        issue = make_issue()
        result = render([issue], "single.md.j2", base_context(issue))
        expected = (GOLDEN / "single.md").read_text(encoding="utf-8")
        assert result == expected

    def test_release_notes_template_matches_golden(self) -> None:
        issue = make_issue()
        result = render([issue], "release-notes.md.j2", base_context(issue))
        expected = (GOLDEN / "release-notes.md").read_text(encoding="utf-8")
        assert result == expected


class TestRelationships:
    """Parent and issue-link rendering in the shipped issue template."""

    def _issue_from(self, **field_overrides: Any) -> Issue:
        payload = load_issue_payload()
        payload["fields"].update(field_overrides)
        return Issue.from_api(payload, base_url="https://example.atlassian.net")

    def test_parent_rendered_below_title(self) -> None:
        issue = make_issue()
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "**Parent:** ABC-100" in result
        assert "Parent epic" in result

    def test_outward_link_rendered(self) -> None:
        issue = make_issue()
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "## Linked work items" in result
        assert "- **blocks** ABC-125" in result
        assert "Blocked issue *(To Do)*" in result

    def test_inward_link_uses_inward_phrase(self) -> None:
        issue = make_issue()
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "- **is duplicated by** ABC-126" in result
        assert "Duplicate issue *(Closed)*" in result

    def test_links_render_without_parent(self) -> None:
        issue = self._issue_from(parent=None)
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "**Parent:**" not in result
        assert "## Linked work items" in result
        assert "\n\n\n" not in result

    def test_parent_renders_without_links(self) -> None:
        issue = self._issue_from(issuelinks=[])
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "**Parent:** ABC-100" in result
        assert "## Linked work items" not in result
        assert "\n\n\n" not in result


class TestOverrides:
    def test_user_dir_overrides_shipped_template(self, tmp_path: Path) -> None:
        (tmp_path / "issue.md.j2").write_text(
            "OVERRIDDEN {{ issue.key }}", encoding="utf-8"
        )
        issue = make_issue()
        result = render(
            [issue],
            "issue.md.j2",
            base_context(issue),
            template_dirs=[tmp_path],
        )
        assert result == "OVERRIDDEN ABC-123"

    def test_shipped_template_still_found_without_override(self) -> None:
        env = build_environment()
        assert env.get_template("issue.md.j2") is not None


class TestMissingFields:
    def test_missing_custom_field_renders_empty(self) -> None:
        issue = make_issue()
        env = build_environment()
        template = env.from_string("[{{ issue.custom.NoSuchField.nested }}]")
        assert template.render(issue=issue) == "[]"

    def test_missing_attribute_chain_never_raises(self) -> None:
        issue = make_issue()
        env = build_environment()
        template = env.from_string("{{ issue.fields.epic.name }}")
        assert template.render(issue=issue) == ""


class TestEmptyIssue:
    def _empty_payload(self) -> dict[str, Any]:
        return {
            "key": "EMPTY-1",
            "fields": {
                "summary": "Bare issue",
                "description": None,
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "created": "2024-01-01T00:00:00.000+0000",
                "updated": "2024-01-01T00:00:00.000+0000",
            },
        }

    def test_empty_sections_omitted(self) -> None:
        issue = Issue.from_api(self._empty_payload())
        result = render([issue], "issue.md.j2", base_context(issue))
        assert "## Description" not in result
        assert "## Attachments" not in result
        assert "## Sub-tasks" not in result
        assert "## Linked work items" not in result
        assert "**Parent:**" not in result
        assert "## Comments" not in result
        assert "\n\n\n" not in result


def _cli_params(**overrides: Any) -> dict[str, Any]:
    params = {
        "url": "https://jira.example.com",
        "email": "alice@example.com",
        "token": "secret-token",
        "auth": None,
        "check": False,
        "sources": ("ABC-123",),
        "fields": None,
        "timeout": 30.0,
        "max_retries": 1,
        "template": None,
        "template_dirs": (),
        "variables": (),
        "single": False,
        "index": False,
        "no_frontmatter": False,
        "out": ".",
        "to_stdout": True,
        "name_template": "{{ issue.key }}.md",
        "assets_dir": "assets",
        "dry_run": False,
    }
    params.update(overrides)
    return params


def _make_client(handler) -> HttpxJiraClient:
    creds = Credentials(
        url="https://jira.example.com",
        email="alice@example.com",
        token="secret-token",
    )
    return HttpxJiraClient(
        creds,
        transport=httpx.MockTransport(handler),
        retry_delay_base=0.0,
        max_retries=1,
    )


class TestCliRendering:
    @pytest.mark.asyncio
    async def test_stdout_render(self, capsys) -> None:
        payload = load_issue_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(_cli_params(), client=client)
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        assert "# ABC-123" in captured.out

    @pytest.mark.asyncio
    async def test_writes_files_to_out_dir(self, tmp_path: Path) -> None:
        payload = load_issue_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(
            _cli_params(to_stdout=False, out=str(tmp_path), index=True),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert (tmp_path / "ABC-123.md").exists()
        assert (tmp_path / "index.md").exists()

    @pytest.mark.asyncio
    async def test_name_template_controls_filename(self, tmp_path: Path) -> None:
        payload = load_issue_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(
            _cli_params(
                to_stdout=False,
                out=str(tmp_path),
                name_template="{{ issue.key | slug }}.md",
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert (tmp_path / "abc-123.md").exists()

    @pytest.mark.asyncio
    async def test_template_error_exit_4(self, tmp_path: Path, capsys) -> None:
        payload = load_issue_payload()
        (tmp_path / "broken.md.j2").write_text(
            "{{ issue | nosuchfilter }}", encoding="utf-8"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(
            _cli_params(template="broken.md.j2", template_dirs=(str(tmp_path),)),
            client=client,
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_TEMPLATE
        assert "template error" in captured.err

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        payload = load_issue_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(
            _cli_params(to_stdout=False, out=str(tmp_path), dry_run=True),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    async def test_var_option_reaches_context(self, tmp_path: Path) -> None:
        payload = load_issue_payload()
        (tmp_path / "custom.md.j2").write_text(
            "release: {{ release }}", encoding="utf-8"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = _make_client(handler)
        code = await run(
            _cli_params(
                to_stdout=False,
                out=str(tmp_path),
                template="custom.md.j2",
                template_dirs=(str(tmp_path),),
                variables=("release=2026.1",),
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert (tmp_path / "ABC-123.md").read_text(encoding="utf-8") == (
            "release: 2026.1"
        )
