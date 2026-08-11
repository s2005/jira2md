"""Tests for the raw response cache."""

from __future__ import annotations

import json

from jira2md.cache import (
    issue_cache_paths,
    read_issue_cache,
    sanitize_meta,
    write_issue_cache,
)


class TestWriteRead:
    def test_roundtrip(self, tmp_path) -> None:
        payload = {"key": "ABC-1", "fields": {"summary": "Hello"}}
        write_issue_cache(
            tmp_path,
            "jira.example.com",
            "ABC-1",
            payload,
            meta={"fetched_at": "2026-01-01T00:00:00+00:00", "etag": 'W/"1"'},
        )
        loaded = read_issue_cache(tmp_path, "jira.example.com", "ABC-1")
        assert loaded is not None
        payload_read, meta = loaded
        assert payload_read == payload
        assert meta["fetched_at"] == "2026-01-01T00:00:00+00:00"
        assert meta["etag"] == 'W/"1"'

    def test_layout_uses_host_and_key(self, tmp_path) -> None:
        payload_path, meta_path = issue_cache_paths(tmp_path, "host.example", "X-9")
        assert payload_path == tmp_path / "host.example" / "X-9.json"
        assert meta_path == tmp_path / "host.example" / "X-9_meta.json"

    def test_missing_entry_returns_none(self, tmp_path) -> None:
        assert read_issue_cache(tmp_path, "host.example", "X-9") is None

    def test_corrupt_payload_returns_none(self, tmp_path) -> None:
        write_issue_cache(tmp_path, "h", "K-1", {"a": 1}, meta={})
        payload_path, _ = issue_cache_paths(tmp_path, "h", "K-1")
        payload_path.write_text("not json {", encoding="utf-8")
        assert read_issue_cache(tmp_path, "h", "K-1") is None

    def test_missing_meta_yields_empty_dict(self, tmp_path) -> None:
        write_issue_cache(tmp_path, "h", "K-1", {"a": 1}, meta={})
        _, meta_path = issue_cache_paths(tmp_path, "h", "K-1")
        meta_path.unlink()
        loaded = read_issue_cache(tmp_path, "h", "K-1")
        assert loaded == ({"a": 1}, {})


class TestSecretHygiene:
    def test_sanitize_meta_allowlist(self) -> None:
        meta = {
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "etag": "abc",
            "authorization": "Basic c2VjcmV0",
            "token": "hunter2",
            "email": "alice@example.com",
        }
        clean = sanitize_meta(meta)
        assert set(clean) == {"fetched_at", "etag"}

    def test_secrets_never_reach_disk(self, tmp_path) -> None:
        write_issue_cache(
            tmp_path,
            "h",
            "K-1",
            {"fields": {"summary": "plain"}},
            meta={
                "fetched_at": "2026-01-01T00:00:00+00:00",
                "authorization": "Bearer super-secret-token",
                "cookie": "session=abc",
            },
        )
        payload_path, meta_path = issue_cache_paths(tmp_path, "h", "K-1")
        for path in (payload_path, meta_path):
            content = path.read_text(encoding="utf-8")
            assert "super-secret-token" not in content
            assert "authorization" not in content.lower()
            assert "cookie" not in content.lower()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert set(meta) == {"fetched_at"}
