"""Tests for the jira2md CLI."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from jira2md.cli import (
    EXIT_AUTH,
    EXIT_DEPRECATED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_RUNTIME,
    exit_code_for,
    main,
    run,
)
from jira2md.client import (
    AuthError,
    DeprecatedEndpointError,
    HttpxJiraClient,
    JiraError,
    NotFoundError,
)
from jira2md.config import Credentials

FIXTURES = Path(__file__).parent / "fixtures"


def load_issue_payload() -> dict[str, Any]:
    with (FIXTURES / "issue_full.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def make_client(handler) -> HttpxJiraClient:
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


def base_params(**overrides: Any) -> dict[str, Any]:
    params = {
        "url": "https://jira.example.com",
        "email": "alice@example.com",
        "token": "secret-token",
        "auth": None,
        "check": False,
        "sources": (),
        "fields": None,
        "timeout": 30.0,
        "max_retries": 1,
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


class TestExitCodeMapping:
    def test_exit_codes(self) -> None:
        assert exit_code_for(AuthError("x")) == EXIT_AUTH
        assert exit_code_for(NotFoundError("x")) == EXIT_NOT_FOUND
        assert exit_code_for(DeprecatedEndpointError("x")) == EXIT_DEPRECATED
        assert exit_code_for(JiraError("x")) == EXIT_RUNTIME
        assert exit_code_for(ValueError("x")) == EXIT_RUNTIME


class TestHelp:
    def test_help_lists_option_groups(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        for option in (
            "--jql",
            "--fields",
            "--history",
            "--max-pages",
            "--url",
            "--email",
            "--token",
            "--auth",
            "--deployment",
            "--check",
            "--template",
            "--template-dir",
            "--var",
            "--single",
            "--index",
            "--no-frontmatter",
            "--out",
            "--stdout",
            "--name-template",
            "--assets-dir",
            "--no-assets",
            "--cache-dir",
            "--offline",
            "--concurrency",
            "--timeout",
            "--max-retries",
            "--dry-run",
        ):
            assert option in result.output

    def test_version(self) -> None:
        result = CliRunner().invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "jira2md" in result.output


class TestCheck:
    @pytest.mark.asyncio
    async def test_check_success(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/api/2/myself"
            return httpx.Response(200, json={"displayName": "Alice Example"})

        client = make_client(handler)
        code = await run(base_params(check=True), client=client)
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        assert "Authenticated as Alice Example" in captured.out

    @pytest.mark.asyncio
    async def test_check_auth_failure_exit_2(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"errorMessages": ["Bad credentials"]})

        client = make_client(handler)
        code = await run(base_params(check=True), client=client)
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_AUTH
        assert "Bad credentials" in captured.err


class TestSingleKeyFetch:
    @pytest.mark.asyncio
    async def test_fetch_outputs_issue(self, capsys) -> None:
        payload = load_issue_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = make_client(handler)
        code = await run(
            base_params(sources=("ABC-123",), to_stdout=True), client=client
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        assert "ABC-123" in captured.out
        assert "Sample issue for tests" in captured.out

    @pytest.mark.asyncio
    async def test_not_found_exit_3(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

        client = make_client(handler)
        code = await run(base_params(sources=("ABC-999",)), client=client)
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_NOT_FOUND
        assert "Issue does not exist" in captured.err

    @pytest.mark.asyncio
    async def test_no_sources_exit_1(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = make_client(handler)
        code = await run(base_params(), client=client)
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "no issue keys" in captured.err

    @pytest.mark.asyncio
    async def test_missing_url_exit_1(self, capsys) -> None:
        # Credentials are isolated from the real config by an autouse
        # fixture in conftest.py, so no URL can be resolved here.
        params = base_params(url=None)
        code = await run(params)
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "No Jira URL" in captured.err


class TestJqlDispatch:
    @pytest.mark.asyncio
    async def test_jql_uses_search_endpoint(self, capsys) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/rest/api/2/search/jql":
                return httpx.Response(200, json={"issues": [load_issue_payload()]})
            return httpx.Response(200, json={})

        client = make_client(handler)
        code = await run(
            base_params(
                sources=("project = ABC",),
                as_jql=True,
                deployment="cloud",
                to_stdout=True,
            ),
            client=client,
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        assert "/rest/api/2/search/jql" in paths
        assert "ABC-123" in captured.out

    @pytest.mark.asyncio
    async def test_keys_do_not_hit_search_endpoint(self, capsys) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json=load_issue_payload())

        client = make_client(handler)
        code = await run(
            base_params(sources=("ABC-123",), to_stdout=True), client=client
        )
        await client.aclose()
        assert code == EXIT_OK
        assert not any("search" in path for path in paths)

    @pytest.mark.asyncio
    async def test_empty_jql_exit_1(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = make_client(handler)
        code = await run(
            base_params(sources=("   ",), as_jql=True, deployment="cloud"),
            client=client,
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "empty JQL" in captured.err


class TestConcurrencyAndHistory:
    @pytest.mark.asyncio
    async def test_concurrent_fetch_preserves_input_order(self, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            key = request.url.path.rsplit("/", 1)[-1]
            payload = dict(load_issue_payload())
            payload["key"] = key
            return httpx.Response(200, json=payload)

        client = make_client(handler)
        keys = ("KEY-3", "KEY-1", "KEY-2")
        code = await run(
            base_params(sources=keys, to_stdout=True, concurrency=3),
            client=client,
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        positions = [captured.out.index(key) for key in keys]
        assert positions == sorted(positions)

    @pytest.mark.asyncio
    async def test_history_attaches_changelog(self, tmp_path, capsys) -> None:
        (tmp_path / "hist.md.j2").write_text(
            "hist={{ raw.changelog | length }}", encoding="utf-8"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/changelog"):
                return httpx.Response(
                    200, json={"values": [{"id": "1"}, {"id": "2"}], "total": 2}
                )
            return httpx.Response(200, json=load_issue_payload())

        client = make_client(handler)
        code = await run(
            base_params(
                sources=("ABC-123",),
                history=True,
                template="hist.md.j2",
                template_dirs=(str(tmp_path),),
                to_stdout=True,
            ),
            client=client,
        )
        await client.aclose()
        captured = capsys.readouterr()
        assert code == EXIT_OK
        assert "hist=2" in captured.out


def issue_payload_with_attachment() -> dict[str, Any]:
    payload = load_issue_payload()
    payload["fields"]["description"] = "See !diagram.png! for details."
    return payload


class TestCliAssets:
    @pytest.mark.asyncio
    async def test_downloads_and_rewrites_references(self, tmp_path) -> None:
        payload = issue_payload_with_attachment()
        downloads: list[str] = []
        # The fixture declares size 12345; a real download returns that many
        # bytes, and the writer rejects a body that disagrees.
        body = b"PNG-BYTES".ljust(12345, b"\0")

        def handler(request: httpx.Request) -> httpx.Response:
            if "/secure/attachment/" in request.url.path:
                downloads.append(str(request.url))
                return httpx.Response(200, content=body)
            return httpx.Response(200, json=payload)

        out = tmp_path / "out"
        client = make_client(handler)
        code = await run(base_params(sources=("ABC-123",), out=str(out)), client=client)
        await client.aclose()
        assert code == EXIT_OK
        assert len(downloads) == 1
        asset = out / "assets" / "ABC-123" / "diagram.png"
        assert asset.read_bytes() == body
        rendered = (out / "ABC-123.md").read_text(encoding="utf-8")
        assert "![](assets/ABC-123/diagram.png)" in rendered

    @pytest.mark.asyncio
    async def test_no_assets_skips_download(self, tmp_path) -> None:
        payload = issue_payload_with_attachment()
        downloads: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "/secure/attachment/" in request.url.path:
                downloads.append(str(request.url))
            return httpx.Response(200, json=payload)

        out = tmp_path / "out"
        client = make_client(handler)
        code = await run(
            base_params(sources=("ABC-123",), out=str(out), no_assets=True),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert downloads == []
        assert not (out / "assets").exists()
        rendered = (out / "ABC-123.md").read_text(encoding="utf-8")
        assert "secure/attachment/20001/diagram.png" in rendered


class TestCacheAndOffline:
    @pytest.mark.asyncio
    async def test_cache_written_without_secrets(self, tmp_path) -> None:
        payload = load_issue_payload()
        cache = tmp_path / "cache"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload, headers={"ETag": 'W/"42"'})

        client = make_client(handler)
        code = await run(
            base_params(
                sources=("ABC-123",), out=str(tmp_path / "out"), cache_dir=str(cache)
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        payload_path = cache / "jira.example.com" / "ABC-123.json"
        meta_path = cache / "jira.example.com" / "ABC-123_meta.json"
        assert payload_path.is_file()
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["etag"] == 'W/"42"'
        assert "fetched_at" in meta
        for path in (payload_path, meta_path):
            content = path.read_text(encoding="utf-8")
            assert "secret-token" not in content
            assert "authorization" not in content.lower()

    @pytest.mark.asyncio
    async def test_offline_rerender_byte_identical(self, tmp_path) -> None:
        payload = issue_payload_with_attachment()
        cache = tmp_path / "cache"

        def handler(request: httpx.Request) -> httpx.Response:
            if "/secure/attachment/" in request.url.path:
                return httpx.Response(200, content=b"PNG-BYTES")
            return httpx.Response(200, json=payload)

        client = make_client(handler)
        code = await run(
            base_params(
                sources=("ABC-123",), out=str(tmp_path / "online"), cache_dir=str(cache)
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK

        # No injected client: run() builds one on the raising OfflineTransport,
        # so any network attempt fails the test.
        code = await run(
            base_params(
                sources=("ABC-123",),
                out=str(tmp_path / "offline"),
                cache_dir=str(cache),
                offline=True,
            )
        )
        assert code == EXIT_OK
        online = (tmp_path / "online" / "ABC-123.md").read_bytes()
        offline = (tmp_path / "offline" / "ABC-123.md").read_bytes()
        assert online == offline

    @pytest.mark.asyncio
    async def test_offline_without_cache_dir_exit_1(self, capsys) -> None:
        code = await run(base_params(sources=("ABC-123",), offline=True))
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "--cache-dir" in captured.err

    @pytest.mark.asyncio
    async def test_offline_cache_miss_exit_1(self, tmp_path, capsys) -> None:
        code = await run(
            base_params(
                sources=("MISSING-1",),
                offline=True,
                cache_dir=str(tmp_path / "cache"),
            )
        )
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "no cached payload" in captured.err

    @pytest.mark.asyncio
    async def test_offline_jql_exit_1(self, tmp_path, capsys) -> None:
        code = await run(
            base_params(
                sources=("project = ABC",),
                as_jql=True,
                offline=True,
                cache_dir=str(tmp_path / "cache"),
            )
        )
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert "cached issue keys only" in captured.err


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, tmp_path) -> None:
        payload = issue_payload_with_attachment()
        downloads: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "/secure/attachment/" in request.url.path:
                downloads.append(str(request.url))
            return httpx.Response(200, json=payload)

        out = tmp_path / "out"
        cache = tmp_path / "cache"
        client = make_client(handler)
        code = await run(
            base_params(
                sources=("ABC-123",),
                out=str(out),
                cache_dir=str(cache),
                dry_run=True,
            ),
            client=client,
        )
        await client.aclose()
        assert code == EXIT_OK
        assert downloads == []
        assert not out.exists()
        assert not cache.exists()
