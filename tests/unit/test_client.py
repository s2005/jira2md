"""Tests for the jira2md httpx client."""

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from jira2md.client import (
    AuthError,
    DeprecatedEndpointError,
    HttpxJiraClient,
    JiraError,
    NotFoundError,
    OfflineTransport,
    OffsetPager,
    PaginationError,
    TokenPager,
    search_issues,
)
from jira2md.config import Credentials
from jira2md.detect import DEPLOYMENT_CLOUD, DEPLOYMENT_DC

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler,
    *,
    credentials: Credentials | None = None,
    max_retries: int = 5,
) -> HttpxJiraClient:
    creds = credentials or Credentials(
        url="https://jira.example.com",
        email="alice@example.com",
        token="secret-token",
    )
    return HttpxJiraClient(
        creds,
        transport=httpx.MockTransport(handler),
        retry_delay_base=0.0,
        max_retries=max_retries,
    )


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_429_then_success(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, json={})
            return httpx.Response(200, json={"key": "ABC-1"})

        async with make_client(handler) as client:
            payload = await client.get_issue("ABC-1")
        assert payload["key"] == "ABC-1"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_500_exhausts_retries(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(500, json={})

        async with make_client(handler, max_retries=2) as client:
            with pytest.raises(JiraError, match="failed after 2 retries"):
                await client.get_issue("ABC-1")
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_retryable_status_codes(self) -> None:
        statuses = [502, 503, 504]

        def handler(request: httpx.Request) -> httpx.Response:
            if statuses:
                return httpx.Response(statuses.pop(0), json={})
            return httpx.Response(200, json={"key": "ABC-1"})

        async with make_client(handler) as client:
            payload = await client.get_issue("ABC-1")
        assert payload["key"] == "ABC-1"
        assert statuses == []

    @pytest.mark.asyncio
    async def test_other_4xx_fails_immediately(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(
                400, json={"errorMessages": ["The JQL query is invalid."]}
            )

        async with make_client(handler) as client:
            with pytest.raises(JiraError, match="The JQL query is invalid."):
                await client.get_issue("ABC-1")
        assert len(calls) == 1


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"errorMessages": ["Bad credentials"]})

        async with make_client(handler) as client:
            with pytest.raises(AuthError, match="Bad credentials"):
                await client.check_auth()

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

        async with make_client(handler) as client:
            with pytest.raises(NotFoundError, match="Issue does not exist"):
                await client.get_issue("ABC-999")

    @pytest.mark.asyncio
    async def test_403_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={})

        async with make_client(handler) as client:
            with pytest.raises(NotFoundError):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_410_raises_deprecated_endpoint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(410, json={})

        async with make_client(handler) as client:
            with pytest.raises(DeprecatedEndpointError):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_field_errors_surfaced(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"errorMessages": [], "errors": {"summary": "required"}}
            )

        async with make_client(handler) as client:
            with pytest.raises(JiraError, match="summary: required"):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_invalid_json_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>", headers={})

        async with make_client(handler) as client:
            with pytest.raises(JiraError, match="Invalid JSON"):
                await client.get_issue("ABC-1")


class TestHeaders:
    @pytest.mark.asyncio
    async def test_basic_auth_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers["Authorization"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        expected = base64.b64encode(b"alice@example.com:secret-token").decode("ascii")
        assert seen["authorization"] == f"Basic {expected}"

    @pytest.mark.asyncio
    async def test_bearer_auth_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers["Authorization"]
            return httpx.Response(200, json={})

        credentials = Credentials(url="https://jira.example.com", token="pat-token")
        async with make_client(handler, credentials=credentials) as client:
            await client.check_auth()
        assert seen["authorization"] == "Bearer pat-token"

    @pytest.mark.asyncio
    async def test_user_agent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["user-agent"] = request.headers["User-Agent"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        assert seen["user-agent"].startswith("jira2md-api/")

    @pytest.mark.asyncio
    async def test_accept_json(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["accept"] = request.headers["Accept"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        assert seen["accept"] == "application/json"


class TestCommentReFetch:
    @staticmethod
    def _comment(comment_id: str, body: str) -> dict[str, Any]:
        return {
            "id": comment_id,
            "body": body,
            "author": {"displayName": "Alice"},
            "created": "2024-02-01T08:00:00.000+0000",
        }

    @pytest.mark.asyncio
    async def test_truncated_comments_refetched(self) -> None:
        issue_payload = {
            "key": "ABC-1",
            "fields": {
                "summary": "S",
                "comment": {
                    "comments": [self._comment("1", "first")],
                    "total": 3,
                    "maxResults": 1,
                    "startAt": 0,
                },
            },
        }
        comment_calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/issue/ABC-1":
                return httpx.Response(200, json=issue_payload)
            if request.url.path == "/rest/api/2/issue/ABC-1/comment":
                start_at = int(request.url.params.get("startAt", "0"))
                comment_calls.append(start_at)
                if start_at == 0:
                    return httpx.Response(
                        200,
                        json={
                            "comments": [
                                self._comment("1", "first"),
                                self._comment("2", "second"),
                            ],
                            "total": 3,
                            "startAt": 0,
                            "maxResults": 2,
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "comments": [self._comment("3", "third")],
                        "total": 3,
                        "startAt": 2,
                        "maxResults": 2,
                    },
                )
            return httpx.Response(404, json={})

        async with make_client(handler) as client:
            payload = await client.get_issue("ABC-1")
        comments = payload["fields"]["comment"]["comments"]
        assert [c["id"] for c in comments] == ["1", "2", "3"]
        assert payload["fields"]["comment"]["total"] == 3
        assert comment_calls == [0, 2]

    @pytest.mark.asyncio
    async def test_complete_comments_not_refetched(self) -> None:
        issue_payload = {
            "key": "ABC-1",
            "fields": {
                "summary": "S",
                "comment": {
                    "comments": [self._comment("1", "first")],
                    "total": 1,
                },
            },
        }
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json=issue_payload)

        async with make_client(handler) as client:
            await client.get_issue("ABC-1")
        assert paths == ["/rest/api/2/issue/ABC-1"]

    @pytest.mark.asyncio
    async def test_get_all_comments_empty_page(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"comments": [], "total": 0, "startAt": 0})

        async with make_client(handler) as client:
            comments = await client.get_all_comments("ABC-1")
        assert comments == []


class TestDefaultFields:
    @pytest.mark.asyncio
    async def test_default_fields_allowlist_sent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["fields"] = request.url.params.get("fields", "")
            return httpx.Response(200, json={"key": "ABC-1", "fields": {}})

        async with make_client(handler) as client:
            await client.get_issue("ABC-1")
        assert "summary" in seen["fields"]
        assert "description" in seen["fields"]
        assert "comment" in seen["fields"]
        assert "issuelinks" in seen["fields"]

    @pytest.mark.asyncio
    async def test_custom_fields_override(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["fields"] = request.url.params.get("fields", "")
            return httpx.Response(200, json={"key": "ABC-1", "fields": {}})

        async with make_client(handler) as client:
            await client.get_issue("ABC-1", fields="summary,description")
        assert seen["fields"] == "summary,description"

    @pytest.mark.asyncio
    async def test_host_property(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            assert client.host == "jira.example.com"


def _issue(key: str) -> dict[str, Any]:
    return {"key": key, "fields": {"summary": key}}


def _json_body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode("utf-8"))


class TestTokenPager:
    @pytest.mark.asyncio
    async def test_multi_page_cursor_traversal(self) -> None:
        requests: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(dict(request.url.params))
            token = request.url.params.get("nextPageToken")
            if token is None:
                return httpx.Response(
                    200,
                    json={
                        "issues": [_issue("A-1"), _issue("A-2")],
                        "nextPageToken": "tok-1",
                    },
                )
            if token == "tok-1":
                return httpx.Response(
                    200,
                    json={"issues": [_issue("A-3")], "nextPageToken": "tok-2"},
                )
            return httpx.Response(200, json={"issues": [_issue("A-4")]})

        async with make_client(handler) as client:
            pager = TokenPager(client, jql="project = A", fields="summary", page_size=2)
            issues = await pager.fetch_all()

        assert [issue["key"] for issue in issues] == ["A-1", "A-2", "A-3", "A-4"]
        # fields is mandatory and always sent on /search/jql
        assert requests[0]["fields"] == "summary"
        assert requests[0]["jql"] == "project = A"
        assert "nextPageToken" not in requests[0]
        assert requests[1]["nextPageToken"] == "tok-1"
        assert requests[2]["nextPageToken"] == "tok-2"

    @pytest.mark.asyncio
    async def test_missing_token_ends_pagination(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            # isLast is False but nextPageToken missing -> still must stop
            return httpx.Response(
                200, json={"issues": [_issue("A-1")], "isLast": False}
            )

        async with make_client(handler) as client:
            pager = TokenPager(client, jql="project = A", fields="summary")
            issues = await pager.fetch_all()

        assert len(issues) == 1
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_repeated_token_aborts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"issues": [_issue("A-1")], "nextPageToken": "stuck"},
            )

        async with make_client(handler) as client:
            pager = TokenPager(client, jql="project = A", fields="summary")
            with pytest.raises(PaginationError, match="repeated nextPageToken"):
                await pager.fetch_all()

    @pytest.mark.asyncio
    async def test_max_pages_cap(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.params.get("nextPageToken"))
            return httpx.Response(
                200,
                json={
                    "issues": [_issue(f"A-{len(calls)}")],
                    "nextPageToken": f"tok-{len(calls)}",
                },
            )

        async with make_client(handler) as client:
            pager = TokenPager(client, jql="project = A", fields="summary", max_pages=2)
            issues = await pager.fetch_all()

        assert len(issues) == 2
        assert len(calls) == 2


class TestOffsetPager:
    @pytest.mark.asyncio
    async def test_offset_traversal_until_total(self) -> None:
        bodies: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = _json_body(request)
            bodies.append(body)
            start = body.get("startAt")
            if start == 0:
                return httpx.Response(
                    200,
                    json={
                        "issues": [_issue("B-1"), _issue("B-2")],
                        "startAt": 0,
                        "total": 3,
                    },
                )
            return httpx.Response(
                200,
                json={"issues": [_issue("B-3")], "startAt": 2, "total": 3},
            )

        async with make_client(handler) as client:
            pager = OffsetPager(
                client, jql="project = B", fields="summary,status", page_size=2
            )
            issues = await pager.fetch_all()

        assert [issue["key"] for issue in issues] == ["B-1", "B-2", "B-3"]
        assert bodies[0]["fields"] == ["summary", "status"]
        assert bodies[0]["startAt"] == 0
        assert bodies[1]["startAt"] == 2

    @pytest.mark.asyncio
    async def test_empty_first_page(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"issues": [], "total": 0})

        async with make_client(handler) as client:
            pager = OffsetPager(client, jql="project = B", fields="summary")
            assert await pager.fetch_all() == []


class TestSearchDispatch:
    @pytest.mark.asyncio
    async def test_cloud_uses_token_endpoint(self) -> None:
        paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={"issues": [_issue("A-1")]})

        async with make_client(handler) as client:
            issues = await search_issues(
                client, "project = A", deployment=DEPLOYMENT_CLOUD
            )

        assert [issue["key"] for issue in issues] == ["A-1"]
        assert paths == ["/rest/api/2/search/jql"]

    @pytest.mark.asyncio
    async def test_dc_uses_offset_endpoint(self) -> None:
        paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={"issues": [_issue("B-1")], "total": 1})

        async with make_client(handler) as client:
            issues = await search_issues(
                client, "project = B", deployment=DEPLOYMENT_DC
            )

        assert [issue["key"] for issue in issues] == ["B-1"]
        assert paths == ["/rest/api/2/search"]

    @pytest.mark.asyncio
    async def test_410_names_search_jql(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(410, json={"errorMessages": ["Gone"]})

        async with make_client(handler) as client:
            with pytest.raises(DeprecatedEndpointError, match=r"/search/jql"):
                await search_issues(client, "project = A", deployment=DEPLOYMENT_DC)

    @pytest.mark.asyncio
    async def test_star_all_downgraded_to_default_fields(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.params.get("fields", ""))
            return httpx.Response(200, json={"issues": []})

        async with make_client(handler) as client:
            await search_issues(
                client, "project = A", deployment=DEPLOYMENT_CLOUD, fields="*all"
            )

        assert seen[0] != "*all"
        assert "summary" in seen[0]


class TestChangelog:
    @pytest.mark.asyncio
    async def test_changelog_pages_until_total(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params.get("startAt", "0"))
            if start == 0:
                return httpx.Response(
                    200,
                    json={"values": [{"id": "1"}, {"id": "2"}], "total": 3},
                )
            return httpx.Response(200, json={"values": [{"id": "3"}], "total": 3})

        async with make_client(handler) as client:
            history = await client.get_all_changelog("ABC-1")

        assert [entry["id"] for entry in history] == ["1", "2", "3"]


class TestDownloadContent:
    @pytest.mark.asyncio
    async def test_download_sends_auth_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("Authorization", "")
            return httpx.Response(200, content=b"BYTES")

        async with make_client(handler) as client:
            body = await client.download_content(
                "https://jira.example.com/secure/attachment/1/a.png"
            )
        assert body == b"BYTES"
        assert seen["authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_download_follows_redirect_to_media_host(self) -> None:
        """Cloud serves attachments via a 302 to a signed media URL."""
        media = "https://api.media.atlassian.com/file/abc/binary?token=xyz"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.media.atlassian.com":
                return httpx.Response(200, content=b"REAL-PNG-BYTES")
            return httpx.Response(302, headers={"Location": media})

        async with make_client(handler) as client:
            body = await client.download_content(
                "https://jira.example.com/rest/api/2/attachment/content/1"
            )
        assert body == b"REAL-PNG-BYTES"

    @pytest.mark.asyncio
    async def test_redirect_does_not_leak_auth_to_media_host(self) -> None:
        """Jira credentials must not travel to the signed media host."""
        media = "https://api.media.atlassian.com/file/abc/binary?token=xyz"
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.media.atlassian.com":
                seen["media_auth"] = request.headers.get("Authorization", "")
                return httpx.Response(200, content=b"REAL-PNG-BYTES")
            seen["jira_auth"] = request.headers.get("Authorization", "")
            return httpx.Response(302, headers={"Location": media})

        async with make_client(handler) as client:
            await client.download_content(
                "https://jira.example.com/rest/api/2/attachment/content/1"
            )
        assert seen["jira_auth"].startswith("Basic ")
        assert seen["media_auth"] == ""

    @pytest.mark.asyncio
    async def test_download_404_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={})

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(NotFoundError):
                await client.download_content(
                    "https://jira.example.com/secure/attachment/1/a.png"
                )

    @pytest.mark.asyncio
    async def test_download_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(AuthError):
                await client.download_content(
                    "https://jira.example.com/secure/attachment/1/a.png"
                )


class TestOfflineTransport:
    @pytest.mark.asyncio
    async def test_every_request_raises(self) -> None:
        creds = Credentials(url="https://jira.example.com", token="t")
        client = HttpxJiraClient(creds, transport=OfflineTransport())
        with pytest.raises(JiraError, match="offline mode"):
            await client.get_issue("ABC-1")
        await client.aclose()


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_transport_error_exhausts_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with make_client(handler, max_retries=1) as client:
            with pytest.raises(JiraError, match="failed after 1 retries"):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_unparsable_retry_after_is_ignored(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(
                    503, headers={"Retry-After": "not-a-number"}, json={}
                )
            return httpx.Response(200, json={"key": "ABC-1"})

        async with make_client(handler, max_retries=1) as client:
            payload = await client.get_issue("ABC-1")
        assert payload["key"] == "ABC-1"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_invalid_json_body_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>not json</html>", headers={"ETag": "x"}
            )

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(JiraError, match="Invalid JSON"):
                await client.check_auth()

    @pytest.mark.asyncio
    async def test_error_body_without_dict_falls_back(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json=["odd"])

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(NotFoundError, match="Not found or no permission"):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_server_info_non_dict_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        async with make_client(handler) as client:
            assert await client.get_server_info() == {}

    @pytest.mark.asyncio
    async def test_unexpected_issue_payload_shape(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["not-a-dict"])

        async with make_client(handler) as client:
            with pytest.raises(JiraError, match="Unexpected payload"):
                await client.get_issue("ABC-1")

    @pytest.mark.asyncio
    async def test_invalid_comment_total_keeps_inline(self) -> None:
        payload = {
            "key": "ABC-1",
            "fields": {
                "comment": {
                    "comments": [{"id": "1", "body": "x"}],
                    "total": "many",
                }
            },
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        async with make_client(handler) as client:
            result = await client.get_issue("ABC-1")
        assert result["fields"]["comment"]["comments"] == [{"id": "1", "body": "x"}]


class TestDownloadRetries:
    @pytest.mark.asyncio
    async def test_download_503_exhausts_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={})

        async with make_client(handler, max_retries=1) as client:
            with pytest.raises(JiraError, match="download failed after 1"):
                await client.download_content(
                    "https://jira.example.com/secure/attachment/1/a.png"
                )

    @pytest.mark.asyncio
    async def test_download_transport_error_exhausts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(JiraError, match="download failed"):
                await client.download_content(
                    "https://jira.example.com/secure/attachment/1/a.png"
                )

    @pytest.mark.asyncio
    async def test_download_generic_4xx(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(418, json={})

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(JiraError, match="HTTP 418"):
                await client.download_content(
                    "https://jira.example.com/secure/attachment/1/a.png"
                )


class TestPagerEdgeCases:
    @pytest.mark.asyncio
    async def test_changelog_histories_fallback_and_bad_total(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params.get("startAt", "0"))
            if start == 0:
                return httpx.Response(
                    200,
                    json={"histories": [{"id": "1"}], "total": "many"},
                )
            return httpx.Response(200, json={"histories": [], "total": "many"})

        async with make_client(handler) as client:
            history = await client.get_all_changelog("ABC-1")
        assert [entry["id"] for entry in history] == ["1"]

    @pytest.mark.asyncio
    async def test_offset_pager_invalid_total_stops_on_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body["startAt"] == 0:
                return httpx.Response(
                    200,
                    json={"issues": [{"key": "A-1"}], "total": "unknown"},
                )
            return httpx.Response(200, json={"issues": [], "total": "unknown"})

        async with make_client(handler) as client:
            issues = await search_issues(
                client,
                "project = A",
                deployment=DEPLOYMENT_DC,
                fields="summary",
            )
        assert [issue["key"] for issue in issues] == ["A-1"]

    @pytest.mark.asyncio
    async def test_token_pager_max_pages_one(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"issues": [{"key": "A-1"}], "nextPageToken": "tok-2"},
            )

        async with make_client(handler) as client:
            pager = TokenPager(client, jql="project = A", fields="summary", max_pages=1)
            issues = await pager.fetch_all()
        assert [issue["key"] for issue in issues] == ["A-1"]

    @pytest.mark.asyncio
    async def test_offset_pager_max_pages_one(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"issues": [{"key": "A-1"}], "total": 500},
            )

        async with make_client(handler) as client:
            pager = OffsetPager(
                client, jql="project = A", fields="summary", max_pages=1
            )
            issues = await pager.fetch_all()
        assert [issue["key"] for issue in issues] == ["A-1"]

    @pytest.mark.asyncio
    async def test_search_non_dict_page_stops(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["odd"])

        async with make_client(handler) as client:
            issues = await search_issues(
                client, "project = A", deployment=DEPLOYMENT_CLOUD
            )
        assert issues == []
