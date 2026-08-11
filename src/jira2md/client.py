"""HTTP client for jira2md.

Direct ``httpx`` client against Jira REST API v2, isolated behind the
``JiraClient`` protocol so tests inject a fake transport. Retries 429
and 5xx with exponential backoff plus jitter and honours Retry-After.
"""

from __future__ import annotations

import asyncio
import logging
import random
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from typing import Any, Protocol

import httpx

from jira2md.config import Credentials
from jira2md.detect import DEPLOYMENT_CLOUD

logger = logging.getLogger("jira2md")

DEFAULT_FIELDS = (
    "summary,description,comment,issuetype,status,priority,resolution,"
    "assignee,reporter,created,updated,resolutiondate,labels,components,"
    "fixVersions,versions,parent,subtasks,issuelinks,attachment"
)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

SEARCH_PAGE_SIZE = 100

_JITTER = random.SystemRandom()


class JiraError(Exception):
    """Base error for jira2md operations."""


class AuthError(JiraError):
    """Authentication failed (HTTP 401)."""


class NotFoundError(JiraError):
    """Issue not found or no permission (HTTP 403/404)."""


class DeprecatedEndpointError(JiraError):
    """Endpoint removed upstream (HTTP 410 Gone)."""


class PaginationError(JiraError):
    """Search pagination misbehaved (repeated or expired token)."""


class OfflineTransport(httpx.AsyncBaseTransport):
    """Transport guard for ``--offline``: refuses every request."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        msg = (
            f"offline mode attempted a network request: {request.method} {request.url}"
        )
        raise JiraError(msg)


def package_version() -> str:
    """Version string used in the User-Agent header."""
    try:
        return version("jira2md")
    except PackageNotFoundError:
        return "0.0.0"


class JiraClient(Protocol):
    """Network boundary so tests can inject a fake."""

    async def get_issue(
        self,
        key: str,
        fields: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch one issue by key, completing truncated comments."""
        ...

    async def get_all_comments(self, key: str) -> list[dict[str, Any]]:
        """Fetch every comment of an issue via the paging endpoint."""
        ...

    async def get_all_changelog(self, key: str) -> list[dict[str, Any]]:
        """Fetch every changelog history of an issue (behind --history)."""
        ...

    async def download_content(self, url: str) -> bytes:
        """Download a raw resource (attachment) with auth headers."""
        ...

    async def check_auth(self) -> dict[str, Any]:
        """Hit /rest/api/2/myself to verify credentials."""
        ...

    async def get_server_info(self) -> dict[str, Any]:
        """Hit /rest/api/2/serverInfo for deployment detection."""
        ...

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        ...


class HttpxJiraClient:
    """Pooled httpx implementation of the JiraClient protocol."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        retry_delay_base: float = 0.5,
        verify: bool | str = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the client.

        Args:
            credentials: Resolved credentials (URL, scheme, token).
            timeout: Per-request timeout in seconds.
            max_retries: Retry budget for 429/5xx responses.
            retry_delay_base: Base delay in seconds for backoff.
            verify: SSL verification flag or CA bundle path.
            transport: Injectable transport (tests use MockTransport).
        """
        self.credentials = credentials
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        headers = {
            "Accept": "application/json",
            "User-Agent": f"jira2md-api/{package_version()}",
            "Authorization": credentials.auth_header(),
        }
        self._client = httpx.AsyncClient(
            base_url=credentials.url,
            headers=headers,
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    @property
    def host(self) -> str:
        """Hostname of the Jira base URL."""
        return self.credentials.host

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request with retry and typed error mapping."""
        transport_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(
                    method, path, params=params, json=json_body
                )
            except httpx.HTTPError as exc:
                transport_error = exc
                logger.debug("Transport error for %s %s: %s", method, path, exc)
                if attempt >= self.max_retries:
                    break
                await self._sleep_backoff(attempt, retry_after=None)
                continue
            if response.status_code in RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    msg = (
                        f"Jira request {method} {path} failed after "
                        f"{self.max_retries} retries "
                        f"(HTTP {response.status_code})"
                    )
                    raise JiraError(msg)
                logger.debug(
                    "Retryable HTTP %d for %s %s",
                    response.status_code,
                    method,
                    path,
                )
                await self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue
            return self._finalise(response, method, path, meta=meta)
        msg = (
            f"Jira request {method} {path} failed after "
            f"{self.max_retries} retries: {transport_error}"
        )
        raise JiraError(msg)

    def _finalise(
        self,
        response: httpx.Response,
        method: str,
        path: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Map status codes to typed errors and decode JSON."""
        status = response.status_code
        if status == 401:
            raise AuthError(
                self._error_message(
                    response, f"Authentication failed for {method} {path}"
                )
            )
        if status in (403, 404):
            raise NotFoundError(
                self._error_message(
                    response,
                    f"Not found or no permission for {method} {path}",
                )
            )
        if status == 410:
            raise DeprecatedEndpointError(
                self._error_message(
                    response, f"Endpoint removed upstream: {method} {path}"
                )
            )
        if status >= 400:
            raise JiraError(
                self._error_message(response, f"HTTP {status} for {method} {path}")
            )
        if meta is not None:
            meta["etag"] = response.headers.get("ETag")
        try:
            return response.json()
        except ValueError as exc:
            msg = f"Invalid JSON from {method} {path}"
            raise JiraError(msg) from exc

    @staticmethod
    def _error_message(response: httpx.Response, fallback: str) -> str:
        """Surface Jira errorMessages verbatim when present."""
        try:
            body = response.json()
        except ValueError:
            return fallback
        if not isinstance(body, dict):
            return fallback
        parts: list[str] = [fallback]
        messages = body.get("errorMessages")
        if isinstance(messages, list):
            parts.extend(str(message) for message in messages)
        errors = body.get("errors")
        if isinstance(errors, dict):
            parts.extend(f"{key}: {value}" for key, value in errors.items())
        if len(parts) == 1:
            return fallback
        return "; ".join(parts)

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        """Sleep with exponential backoff, honouring Retry-After."""
        delay = self.retry_delay_base * (2**attempt) + _JITTER.uniform(0, 0.1)
        if retry_after is not None:
            try:
                delay = max(float(retry_after), 0.0)
            except ValueError:
                logger.debug("Ignoring unparsable Retry-After: %r", retry_after)
        logger.debug("Retrying in %.2fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)

    async def check_auth(self) -> dict[str, Any]:
        """Verify credentials via /rest/api/2/myself."""
        payload = await self._request("GET", "/rest/api/2/myself")
        return payload if isinstance(payload, dict) else {}

    async def get_server_info(self) -> dict[str, Any]:
        """Fetch /rest/api/2/serverInfo for deployment detection."""
        payload = await self._request("GET", "/rest/api/2/serverInfo")
        return payload if isinstance(payload, dict) else {}

    async def get_issue(
        self,
        key: str,
        fields: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch one issue and complete truncated comment lists."""
        params: dict[str, Any] = {"fields": fields or DEFAULT_FIELDS}
        payload = await self._request(
            "GET", f"/rest/api/2/issue/{key}", params=params, meta=meta
        )
        if not isinstance(payload, dict):
            msg = f"Unexpected payload for issue {key}"
            raise JiraError(msg)
        return await self._ensure_full_comments(payload)

    async def _ensure_full_comments(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Re-fetch comments when the issue payload truncates them."""
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return payload
        comment = fields.get("comment")
        if not isinstance(comment, dict):
            return payload
        try:
            total = int(comment.get("total") or 0)
        except (TypeError, ValueError):
            return payload
        inline = comment.get("comments")
        if not isinstance(inline, list) or total <= len(inline):
            return payload
        key = str(payload.get("key") or "")
        full = await self.get_all_comments(key)
        completed_comment = dict(comment)
        completed_comment["comments"] = full
        completed_comment["total"] = len(full)
        completed_fields = dict(fields)
        completed_fields["comment"] = completed_comment
        completed = dict(payload)
        completed["fields"] = completed_fields
        return completed

    async def get_all_comments(
        self, key: str, *, page_size: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch every comment via /issue/{key}/comment paging."""
        collected: list[dict[str, Any]] = []
        start_at = 0
        while True:
            params: dict[str, Any] = {
                "startAt": start_at,
                "maxResults": page_size,
            }
            page = await self._request(
                "GET", f"/rest/api/2/issue/{key}/comment", params=params
            )
            if not isinstance(page, dict):
                break
            comments = page.get("comments")
            batch = (
                [item for item in comments if isinstance(item, dict)]
                if isinstance(comments, list)
                else []
            )
            collected.extend(batch)
            try:
                total = int(page.get("total") or 0)
            except (TypeError, ValueError):
                total = start_at + len(batch)
            start_at += len(batch)
            if not batch or start_at >= total:
                break
        return collected

    async def get_all_changelog(
        self, key: str, *, page_size: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch every changelog history via /issue/{key}/changelog paging."""
        collected: list[dict[str, Any]] = []
        start_at = 0
        while True:
            params: dict[str, Any] = {
                "startAt": start_at,
                "maxResults": page_size,
            }
            page = await self._request(
                "GET", f"/rest/api/2/issue/{key}/changelog", params=params
            )
            if not isinstance(page, dict):
                break
            values = page.get("values")
            if not isinstance(values, list):
                values = page.get("histories")
            batch = (
                [item for item in values if isinstance(item, dict)]
                if isinstance(values, list)
                else []
            )
            collected.extend(batch)
            try:
                total = int(page.get("total") or 0)
            except (TypeError, ValueError):
                total = start_at + len(batch)
            start_at += len(batch)
            if not batch or start_at >= total:
                break
        return collected

    async def download_content(self, url: str) -> bytes:
        """Download a raw resource with auth headers (attachments).

        Redirects are followed: on Cloud the attachment ``content`` URL
        answers 302 with a signed media-host location, and the redirect
        body is empty. httpx drops the Authorization header on a
        cross-origin hop, so credentials never reach the media host.
        """
        transport_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(
                    url, headers={"Accept": "*/*"}, follow_redirects=True
                )
            except httpx.HTTPError as exc:
                transport_error = exc
                if attempt >= self.max_retries:
                    break
                await self._sleep_backoff(attempt, retry_after=None)
                continue
            status = response.status_code
            if status in RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    msg = (
                        f"Attachment download failed after {self.max_retries} "
                        f"retries (HTTP {status})"
                    )
                    raise JiraError(msg)
                await self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue
            if status == 401:
                msg = f"Authentication failed downloading {url}"
                raise AuthError(msg)
            if status in (403, 404):
                msg = f"Not found or no permission: {url}"
                raise NotFoundError(msg)
            if status >= 400:
                msg = f"HTTP {status} downloading {url}"
                raise JiraError(msg)
            return response.content
        msg = (
            f"Attachment download failed after {self.max_retries} "
            f"retries: {transport_error}"
        )
        raise JiraError(msg)

    async def aclose(self) -> None:
        """Close the pooled httpx client."""
        await self._client.aclose()

    async def __aenter__(self) -> HttpxJiraClient:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()


class TokenPager:
    """Cursor paginator for the Cloud ``GET /rest/api/2/search/jql``.

    Follows ``nextPageToken`` until it is missing, aborts on a repeated
    token, and honours the ``--max-pages`` cap.
    """

    def __init__(
        self,
        client: HttpxJiraClient,
        *,
        jql: str,
        fields: str,
        max_pages: int = 200,
        page_size: int = SEARCH_PAGE_SIZE,
    ) -> None:
        self._client = client
        self._jql = jql
        self._fields = fields
        self._max_pages = max_pages
        self._page_size = page_size

    async def fetch_all(self) -> list[dict[str, Any]]:
        """Fetch every issue across cursor pages."""
        collected: list[dict[str, Any]] = []
        next_token: str | None = None
        pages = 0
        while True:
            if pages >= self._max_pages:
                logger.warning(
                    "Reached --max-pages cap (%d); stopping search", self._max_pages
                )
                break
            params: dict[str, Any] = {
                "jql": self._jql,
                "fields": self._fields,
                "maxResults": self._page_size,
            }
            if next_token:
                params["nextPageToken"] = next_token
            page = await self._client._request(
                "GET", "/rest/api/2/search/jql", params=params
            )
            pages += 1
            if not isinstance(page, dict):
                break
            issues = page.get("issues")
            if isinstance(issues, list):
                collected.extend(issue for issue in issues if isinstance(issue, dict))
            returned_token = page.get("nextPageToken")
            if not returned_token:
                break
            if returned_token == next_token:
                msg = (
                    "Jira /search/jql returned a repeated nextPageToken; "
                    "aborting to avoid an infinite loop"
                )
                raise PaginationError(msg)
            next_token = str(returned_token)
        return collected


class OffsetPager:
    """Offset paginator for the Server/DC ``POST /rest/api/2/search``."""

    def __init__(
        self,
        client: HttpxJiraClient,
        *,
        jql: str,
        fields: str,
        max_pages: int = 200,
        page_size: int = SEARCH_PAGE_SIZE,
    ) -> None:
        self._client = client
        self._jql = jql
        self._fields = [part for part in fields.split(",") if part]
        self._max_pages = max_pages
        self._page_size = page_size

    async def fetch_all(self) -> list[dict[str, Any]]:
        """Fetch every issue across startAt pages."""
        collected: list[dict[str, Any]] = []
        start_at = 0
        pages = 0
        while True:
            if pages >= self._max_pages:
                logger.warning(
                    "Reached --max-pages cap (%d); stopping search", self._max_pages
                )
                break
            body: dict[str, Any] = {
                "jql": self._jql,
                "fields": self._fields,
                "startAt": start_at,
                "maxResults": self._page_size,
            }
            page = await self._client._request(
                "POST", "/rest/api/2/search", json_body=body
            )
            pages += 1
            if not isinstance(page, dict):
                break
            issues = page.get("issues")
            batch = (
                [issue for issue in issues if isinstance(issue, dict)]
                if isinstance(issues, list)
                else []
            )
            collected.extend(batch)
            try:
                total = int(page.get("total") or 0)
            except (TypeError, ValueError):
                total = start_at + len(batch)
            start_at += len(batch)
            if not batch or start_at >= total:
                break
        return collected


async def search_issues(
    client: HttpxJiraClient,
    jql: str,
    *,
    deployment: str,
    fields: str | None = None,
    max_pages: int = 200,
    page_size: int = SEARCH_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Search issues using the pager appropriate for the deployment.

    Args:
        client: Authenticated client.
        jql: JQL query string.
        deployment: ``cloud`` or ``dc`` (selects the pager).
        fields: Comma-separated field allowlist (mandatory on /search/jql).
        max_pages: Pagination safety cap.
        page_size: Issues requested per page.

    Returns:
        List of raw issue payloads in server order.
    """
    # /search/jql requires an explicit field list; '*all' is single-issue only.
    resolved = fields or DEFAULT_FIELDS
    if resolved == "*all":
        resolved = DEFAULT_FIELDS
    if deployment == DEPLOYMENT_CLOUD:
        pager: TokenPager | OffsetPager = TokenPager(
            client, jql=jql, fields=resolved, max_pages=max_pages, page_size=page_size
        )
    else:
        pager = OffsetPager(
            client, jql=jql, fields=resolved, max_pages=max_pages, page_size=page_size
        )
    try:
        return await pager.fetch_all()
    except DeprecatedEndpointError as exc:
        msg = (
            "The legacy /rest/api/2/search endpoint returned 410 Gone; this "
            "Jira instance requires /rest/api/2/search/jql. "
            f"Detail: {exc}"
        )
        raise DeprecatedEndpointError(msg) from exc
