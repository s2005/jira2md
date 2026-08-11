"""End-to-end replay of recorded Cloud and DC cassettes.

All fixtures live in ``cassettes/`` and replay through a mock
transport, so the suite is fully offline while exercising the real CLI
pipeline: fetch, asset download, render, cache, offline re-render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from jira2md.cli import EXIT_OK, run
from jira2md.client import HttpxJiraClient
from jira2md.config import Credentials
from jira2md.detect import clear_deployment_cache

CASSETTES = Path(__file__).parent / "cassettes"

CLOUD_URL = "https://cassette.atlassian.net"
DC_URL = "https://jira.cassette-dc.example"


def load_cassette(name: str) -> dict[str, Any]:
    with (CASSETTES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def make_replay_client(
    deployment: str, base_url: str, *, recorded: list[str]
) -> HttpxJiraClient:
    """Build a client whose transport replays the cassette files."""
    issue = load_cassette(f"{deployment}_issue.json")
    serverinfo = load_cassette(f"{deployment}_serverinfo.json")
    asset_bytes = (CASSETTES / "diagram.png").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == "/rest/api/2/serverInfo":
            return httpx.Response(200, json=serverinfo)
        if path == f"/rest/api/2/issue/{issue['key']}":
            return httpx.Response(200, json=issue)
        if path == "/rest/api/2/search/jql":
            return httpx.Response(200, json={"issues": [issue]})
        if path == "/rest/api/2/search":
            return httpx.Response(
                200, json={"issues": [issue], "startAt": 0, "total": 1}
            )
        if path.startswith("/secure/attachment/"):
            return httpx.Response(200, content=asset_bytes)
        return httpx.Response(404, json={"errorMessages": ["not in cassette"]})

    creds = Credentials(url=base_url, email="replay@example.com", token="replay")
    return HttpxJiraClient(
        creds,
        transport=httpx.MockTransport(handler),
        retry_delay_base=0.0,
        max_retries=0,
    )


def base_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "auth": None,
        "check": False,
        "sources": (),
        "fields": None,
        "timeout": 30.0,
        "max_retries": 0,
        "as_jql": False,
        "history": False,
        "concurrency": 4,
        "deployment": None,
        "max_pages": 200,
        "template": None,
        "template_dirs": (),
        "variables": (),
        "single": False,
        "index": False,
        "no_frontmatter": False,
        "out": ".",
        "to_stdout": False,
        "name_template": "{{ issue.key }}.md",
        "assets_dir": "assets",
        "no_assets": False,
        "cache_dir": None,
        "offline": False,
        "dry_run": False,
    }
    params.update(overrides)
    return params


@pytest.mark.integration
class TestCloudCassette:
    def setup_method(self) -> None:
        clear_deployment_cache()

    @pytest.mark.asyncio
    async def test_end_to_end_issue_and_asset(self, tmp_path) -> None:
        recorded: list[str] = []
        client = make_replay_client("cloud", CLOUD_URL, recorded=recorded)
        out = tmp_path / "out"
        code = await run(
            base_params(
                url=CLOUD_URL,
                email="replay@example.com",
                token="replay",
                sources=("ABC-123",),
                out=str(out),
                index=True,
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK

        rendered = (out / "ABC-123.md").read_text(encoding="utf-8")
        assert rendered.startswith("---\n")
        assert "key: ABC-123" in rendered
        assert "Cassette issue (Cloud)" in rendered
        assert "```python" in rendered
        assert "![](assets/ABC-123/diagram.png)" in rendered
        asset = out / "assets" / "ABC-123" / "diagram.png"
        assert asset.read_bytes() == (CASSETTES / "diagram.png").read_bytes()
        assert (out / "index.md").is_file()

    @pytest.mark.asyncio
    async def test_jql_uses_token_endpoint(self, tmp_path) -> None:
        recorded: list[str] = []
        client = make_replay_client("cloud", CLOUD_URL, recorded=recorded)
        out = tmp_path / "out"
        code = await run(
            base_params(
                url=CLOUD_URL,
                email="replay@example.com",
                token="replay",
                sources=("project = ABC",),
                as_jql=True,
                out=str(out),
                no_assets=True,
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert any("GET /rest/api/2/search/jql" in line for line in recorded)
        assert (out / "ABC-123.md").is_file()

    @pytest.mark.asyncio
    async def test_offline_rerender_byte_identical(self, tmp_path) -> None:
        recorded: list[str] = []
        client = make_replay_client("cloud", CLOUD_URL, recorded=recorded)
        cache = tmp_path / "cache"
        out_online = tmp_path / "online"
        code = await run(
            base_params(
                url=CLOUD_URL,
                email="replay@example.com",
                token="replay",
                sources=("ABC-123",),
                out=str(out_online),
                cache_dir=str(cache),
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK

        out_offline = tmp_path / "offline"
        code = await run(
            base_params(
                url=CLOUD_URL,
                email="replay@example.com",
                token="replay",
                sources=("ABC-123",),
                out=str(out_offline),
                cache_dir=str(cache),
                offline=True,
            )
        )
        assert code == EXIT_OK
        online = (out_online / "ABC-123.md").read_bytes()
        offline = (out_offline / "ABC-123.md").read_bytes()
        assert online == offline


@pytest.mark.integration
class TestDcCassette:
    def setup_method(self) -> None:
        clear_deployment_cache()

    @pytest.mark.asyncio
    async def test_end_to_end_issue_and_asset(self, tmp_path) -> None:
        recorded: list[str] = []
        client = make_replay_client("dc", DC_URL, recorded=recorded)
        out = tmp_path / "out"
        code = await run(
            base_params(
                url=DC_URL,
                email="replay@example.com",
                token="replay",
                sources=("DC-77",),
                out=str(out),
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK

        rendered = (out / "DC-77.md").read_text(encoding="utf-8")
        assert "key: DC-77" in rendered
        assert "Cassette issue (Data Center)" in rendered
        assert "- bullet one" in rendered
        assert "![](assets/DC-77/diagram.png)" in rendered
        assert (out / "assets" / "DC-77" / "diagram.png").is_file()

    @pytest.mark.asyncio
    async def test_jql_uses_offset_endpoint(self, tmp_path) -> None:
        recorded: list[str] = []
        client = make_replay_client("dc", DC_URL, recorded=recorded)
        out = tmp_path / "out"
        code = await run(
            base_params(
                url=DC_URL,
                email="replay@example.com",
                token="replay",
                sources=("project = DC",),
                as_jql=True,
                out=str(out),
                no_assets=True,
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert any("POST /rest/api/2/search" in line for line in recorded)
        assert not any("/search/jql" in line for line in recorded)
        assert (out / "DC-77.md").is_file()
