"""Tests for attachment handling."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jira2md.assets import (
    apply_attachment_paths,
    asset_url_map,
    download_attachments,
    stored_filename,
)
from jira2md.client import HttpxJiraClient
from jira2md.config import Credentials
from jira2md.model import Attachment, Issue

FIXTURES = Path(__file__).parent / "fixtures"


def load_issue_payload() -> dict:
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


def make_issue(attachments: tuple[Attachment, ...]) -> Issue:
    payload = load_issue_payload()
    payload["fields"]["attachment"] = [dict(a.raw) for a in attachments]
    return Issue.from_api(payload, base_url="https://jira.example.com")


def attachment(filename: str, att_id: str = "20001", size: int = 10) -> Attachment:
    return Attachment(
        filename=filename,
        size=size,
        mime_type="application/octet-stream",
        content_url=f"https://jira.example.com/secure/attachment/{att_id}/{filename}",
        raw={
            "id": att_id,
            "filename": filename,
            "size": size,
            "mimeType": "application/octet-stream",
            "content": (
                f"https://jira.example.com/secure/attachment/{att_id}/{filename}"
            ),
        },
    )


class TestStoredFilename:
    def test_first_use_keeps_name(self) -> None:
        used: dict[str, int] = {}
        assert stored_filename(attachment("diagram.png"), used) == "diagram.png"

    def test_collisions_get_suffixes(self) -> None:
        used: dict[str, int] = {}
        first = stored_filename(attachment("diagram.png"), used)
        second = stored_filename(attachment("diagram.png"), used)
        third = stored_filename(attachment("diagram.png"), used)
        assert (first, second, third) == (
            "diagram.png",
            "diagram-1.png",
            "diagram-2.png",
        )

    def test_collision_without_extension(self) -> None:
        used: dict[str, int] = {}
        stored_filename(attachment("README"), used)
        assert stored_filename(attachment("README"), used) == "README-1"

    def test_path_traversal_is_flattened(self) -> None:
        used: dict[str, int] = {}
        assert stored_filename(attachment("../evil.png"), used) == "evil.png"


class TestAssetUrlMap:
    def test_first_filename_wins(self) -> None:
        attachments = (attachment("a.png", "1"), attachment("a.png", "2"))
        mapping = asset_url_map(attachments, ("a.png", "a-1.png"))
        assert mapping == {"a.png": "a.png"}


class TestApplyAttachmentPaths:
    def test_download_paths_include_key(self) -> None:
        issue = make_issue((attachment("diagram.png"),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        assert updated.attachments[0].path == "assets/ABC-123/diagram.png"

    def test_no_assets_keeps_content_url(self) -> None:
        issue = make_issue((attachment("diagram.png"),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=False
        )
        assert updated.attachments[0].path == (
            "https://jira.example.com/secure/attachment/20001/diagram.png"
        )

    def test_issue_without_attachments_unchanged(self) -> None:
        issue = make_issue(())
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        assert updated is issue


class TestDownloadAttachments:
    @pytest.mark.asyncio
    async def test_downloads_with_auth_and_writes_files(self, tmp_path) -> None:
        seen_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers["authorization"] = request.headers.get("Authorization", "")
            return httpx.Response(200, content=b"PNG-BYTES")

        issue = make_issue((attachment("diagram.png", size=len(b"PNG-BYTES")),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        client = make_client(handler)
        written = await download_attachments(
            client, updated, tmp_path, assets_dir="assets"
        )
        await client.aclose()
        assert written == 1
        target = tmp_path / "assets" / "ABC-123" / "diagram.png"
        assert target.read_bytes() == b"PNG-BYTES"
        assert seen_headers["authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_collision_suffixes_on_disk(self, tmp_path) -> None:
        bodies = iter([b"one", b"two"])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=next(bodies))

        issue = make_issue(
            (attachment("a.txt", "1", size=3), attachment("a.txt", "2", size=3))
        )
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        client = make_client(handler)
        await download_attachments(client, updated, tmp_path, assets_dir="assets")
        await client.aclose()
        directory = tmp_path / "assets" / "ABC-123"
        assert (directory / "a.txt").read_bytes() == b"one"
        assert (directory / "a-1.txt").read_bytes() == b"two"

    @pytest.mark.asyncio
    async def test_redirected_attachment_writes_real_bytes(self, tmp_path) -> None:
        """Cloud answers the content URL with a 302 to a signed media host.

        Regression: the redirect body is empty, so not following it wrote a
        0-byte image file and still reported the download as successful.
        """
        media = "https://api.media.atlassian.com/file/abc/binary?token=xyz"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.media.atlassian.com":
                return httpx.Response(200, content=b"REAL-PNG-BYTES")
            return httpx.Response(302, headers={"Location": media})

        issue = make_issue((attachment("diagram.png", size=len(b"REAL-PNG-BYTES")),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        client = make_client(handler)
        written = await download_attachments(
            client, updated, tmp_path, assets_dir="assets"
        )
        await client.aclose()
        assert written == 1
        target = tmp_path / "assets" / "ABC-123" / "diagram.png"
        assert target.read_bytes() == b"REAL-PNG-BYTES"
        assert target.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_truncated_download_is_skipped_not_written(self, tmp_path) -> None:
        """A body shorter than the reported size must not reach disk."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"")

        issue = make_issue((attachment("diagram.png", size=4096),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        client = make_client(handler)
        written = await download_attachments(
            client, updated, tmp_path, assets_dir="assets"
        )
        await client.aclose()
        assert written == 0
        assert not (tmp_path / "assets" / "ABC-123" / "diagram.png").exists()

    @pytest.mark.asyncio
    async def test_genuinely_empty_attachment_is_written(self, tmp_path) -> None:
        """A file Jira reports as 0 bytes is legitimate and still written."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"")

        issue = make_issue((attachment("empty.log", size=0),))
        (updated,) = apply_attachment_paths(
            [issue], assets_dir="assets", download_assets=True
        )
        client = make_client(handler)
        written = await download_attachments(
            client, updated, tmp_path, assets_dir="assets"
        )
        await client.aclose()
        assert written == 1
        assert (tmp_path / "assets" / "ABC-123" / "empty.log").read_bytes() == b""
