"""Command line interface for jira2md."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

import click
from jinja2 import TemplateError

from jira2md.assets import apply_attachment_paths, download_attachments
from jira2md.cache import read_issue_cache, write_issue_cache
from jira2md.client import (
    DEFAULT_FIELDS,
    AuthError,
    DeprecatedEndpointError,
    HttpxJiraClient,
    JiraClient,
    JiraError,
    NotFoundError,
    OfflineTransport,
    search_issues,
)
from jira2md.config import (
    ConfigError,
    Credentials,
    resolve_credentials,
)
from jira2md.detect import detect_deployment
from jira2md.model import Issue
from jira2md.render import build_environment, render

logger = logging.getLogger("jira2md")

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_AUTH = 2
EXIT_NOT_FOUND = 3
EXIT_TEMPLATE = 4
EXIT_DEPRECATED = 5

try:
    __version__ = version("jira2md")
except PackageNotFoundError:
    __version__ = "0.0.0"


def exit_code_for(error: Exception) -> int:
    """Map a typed error to its CLI exit code."""
    if isinstance(error, AuthError):
        return EXIT_AUTH
    if isinstance(error, NotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(error, DeprecatedEndpointError):
        return EXIT_DEPRECATED
    return EXIT_RUNTIME


def _setup_logging(verbose: int) -> None:
    """Configure stderr logging from the -v/-vv flags."""
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s - %(name)s - %(message)s",
        force=True,
    )


async def _run_check(client: JiraClient) -> int:
    """Implement ``--check``: verify credentials and exit."""
    myself = await client.check_auth()
    name = myself.get("displayName") or myself.get("name") or "unknown"
    click.echo(f"Authenticated as {name}")
    return EXIT_OK


def _parse_variables(variables: tuple[str, ...]) -> dict[str, str]:
    """Parse ``--var KEY=VALUE`` pairs into a dict."""
    extra: dict[str, str] = {}
    for item in variables:
        key, _, value = item.partition("=")
        extra[key.strip()] = value
    return extra


def _build_context(
    params: dict[str, Any],
    credentials: Credentials,
    issues: list[Issue],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the shared template context."""
    context: dict[str, Any] = {
        "issues": issues,
        "base_url": credentials.url,
        "now": now or datetime.now(timezone.utc),
        "fields": {},
        "config": {
            "frontmatter": not params.get("no_frontmatter"),
            "assets_dir": params.get("assets_dir") or "assets",
        },
    }
    context.update(_parse_variables(tuple(params.get("variables") or ())))
    return context


def _cache_timestamps(metas: list[dict[str, Any]]) -> datetime | None:
    """Latest cache fetch time, used as ``now`` for offline renders."""
    from jira2md.model import _parse_datetime

    latest: datetime | None = None
    for meta in metas:
        parsed = _parse_datetime(meta.get("fetched_at"))
        if parsed and (latest is None or parsed > latest):
            latest = parsed
    return latest


async def _render_issues(
    params: dict[str, Any],
    issues: list[Issue],
    credentials: Credentials,
    *,
    client: JiraClient | None = None,
    now: datetime | None = None,
) -> int:
    """Render fetched issues to stdout or files."""
    template_dirs = tuple(params.get("template_dirs") or ())
    context = _build_context(params, credentials, issues, now=now)
    to_stdout = bool(params.get("to_stdout"))
    dry_run = bool(params.get("dry_run"))
    out_dir = Path(str(params.get("out") or "."))
    name_template = str(params.get("name_template") or "{{ issue.key }}.md")
    environment = build_environment(template_dirs)

    outputs: list[tuple[str, str]] = []
    try:
        if params.get("single"):
            content = render(issues, "single.md.j2", context, environment=environment)
            outputs.append(("single.md", content))
        else:
            template_name = str(params.get("template") or "issue.md.j2")
            for issue in issues:
                issue_context = dict(context)
                issue_context["issue"] = issue
                issue_context["raw"] = issue.raw
                content = render(
                    [issue], template_name, issue_context, environment=environment
                )
                filename = environment.from_string(name_template).render(issue=issue)
                outputs.append((filename, content))
        if params.get("index"):
            content = render(issues, "index.md.j2", context, environment=environment)
            outputs.append(("index.md", content))
    except TemplateError as exc:
        click.echo(f"template error: {exc}", err=True)
        return EXIT_TEMPLATE

    if to_stdout:
        for _, content in outputs:
            click.echo(content, nl=False)
        return EXIT_OK
    if dry_run:
        for filename, _ in outputs:
            logger.info("dry-run: would write %s", filename)
        return EXIT_OK

    out_dir.mkdir(parents=True, exist_ok=True)
    download_assets = not params.get("no_assets")
    if download_assets and client is not None:
        assets_dir = str(params.get("assets_dir") or "assets")
        for issue in issues:
            await download_attachments(client, issue, out_dir, assets_dir=assets_dir)
    for filename, content in outputs:
        (out_dir / filename).write_text(content, encoding="utf-8")
        logger.info("wrote %s", out_dir / filename)
    return EXIT_OK


async def _fetch_one(
    client: JiraClient,
    key: str,
    fields: str | None,
    semaphore: asyncio.Semaphore,
    *,
    history: bool,
    cache_dir: Path | None,
    host: str,
) -> dict[str, Any]:
    """Fetch a single issue under the concurrency semaphore."""
    async with semaphore:
        meta: dict[str, Any] = {}
        payload = await client.get_issue(key, fields=fields, meta=meta)
        if history:
            payload = dict(payload)
            payload["changelog"] = await client.get_all_changelog(key)
        if cache_dir is not None:
            write_issue_cache(
                cache_dir,
                host,
                key,
                payload,
                meta={
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "etag": meta.get("etag"),
                    "fields": fields or DEFAULT_FIELDS,
                    "endpoint": f"/rest/api/2/issue/{key}",
                },
            )
        return payload


def _prepare_issues(
    params: dict[str, Any],
    payloads: list[dict[str, Any]],
    credentials: Credentials,
) -> list[Issue]:
    """Normalise payloads and resolve attachment link targets."""
    issues = [Issue.from_api(payload, base_url=credentials.url) for payload in payloads]
    return apply_attachment_paths(
        issues,
        assets_dir=str(params.get("assets_dir") or "assets"),
        download_assets=not params.get("no_assets"),
    )


async def _run_fetch(
    params: dict[str, Any],
    client: JiraClient,
    credentials: Credentials,
    sources: tuple[str, ...],
) -> int:
    """Fetch issues by key concurrently and render them as Markdown."""
    if params.get("as_jql"):
        return await _run_jql(params, client, credentials, sources)
    fields = params.get("fields") or None
    history = bool(params.get("history"))
    concurrency = max(1, int(params.get("concurrency") or 4))
    semaphore = asyncio.Semaphore(concurrency)
    cache_dir = _cache_dir_param(params, write=not params.get("dry_run"))
    # asyncio.gather preserves input order regardless of completion order.
    payloads = list(
        await asyncio.gather(
            *(
                _fetch_one(
                    client,
                    key,
                    fields,
                    semaphore,
                    history=history,
                    cache_dir=cache_dir,
                    host=credentials.host,
                )
                for key in sources
            )
        )
    )
    fetched = _prepare_issues(params, payloads, credentials)
    logger.info("%d fetched", len(fetched))
    return await _render_issues(params, fetched, credentials, client=client)


async def _run_jql(
    params: dict[str, Any],
    client: JiraClient,
    credentials: Credentials,
    sources: tuple[str, ...],
) -> int:
    """Run a JQL search using the deployment-appropriate pager."""
    jql = " ".join(sources)
    if not jql.strip():
        click.echo("error: empty JQL query", err=True)
        return EXIT_RUNTIME
    deployment = await detect_deployment(
        client,
        override=params.get("deployment"),
        host=credentials.host,
    )
    fields = params.get("fields") or DEFAULT_FIELDS
    payloads = await search_issues(
        cast(HttpxJiraClient, client),
        jql,
        deployment=deployment,
        fields=fields,
        max_pages=int(params.get("max_pages") or 200),
    )
    cache_dir = _cache_dir_param(params, write=not params.get("dry_run"))
    if cache_dir is not None:
        for payload in payloads:
            key = str(payload.get("key") or "")
            if key:
                write_issue_cache(
                    cache_dir,
                    credentials.host,
                    key,
                    payload,
                    meta={
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "fields": fields,
                        "endpoint": "/rest/api/2/search/jql",
                    },
                )
    fetched = _prepare_issues(params, payloads, credentials)
    logger.info("%d fetched", len(fetched))
    return await _render_issues(params, fetched, credentials, client=client)


def _cache_dir_param(params: dict[str, Any], *, write: bool) -> Path | None:
    """Resolve --cache-dir, skipping writes when ``write`` is false."""
    raw = params.get("cache_dir")
    if not raw or not write:
        return None
    return Path(str(raw))


async def _run_offline(
    params: dict[str, Any],
    credentials: Credentials,
    sources: tuple[str, ...],
) -> int:
    """Render issues exclusively from the cache."""
    cache_dir = params.get("cache_dir")
    if not cache_dir:
        click.echo("error: --offline requires --cache-dir", err=True)
        return EXIT_RUNTIME
    payloads: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    cache_path = Path(str(cache_dir))
    for key in sources:
        cached = read_issue_cache(cache_path, credentials.host, key)
        if cached is None:
            click.echo(f"error: no cached payload for {key}", err=True)
            return EXIT_RUNTIME
        payloads.append(cached[0])
        metas.append(cached[1])
    fetched = _prepare_issues(params, payloads, credentials)
    logger.info("%d loaded from cache", len(fetched))
    return await _render_issues(
        params, fetched, credentials, now=_cache_timestamps(metas)
    )


async def run(params: dict[str, Any], *, client: JiraClient | None = None) -> int:
    """Run the CLI body; returns the process exit code.

    Args:
        params: Click parameter mapping.
        client: Injectable client (tests inject a fake transport).
    """
    try:
        credentials = resolve_credentials(
            url=params.get("url"),
            email=params.get("email"),
            token=params.get("token"),
            auth=params.get("auth"),
            env_file=params.get("env_file"),
        )
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        return EXIT_RUNTIME

    owns_client = client is None
    if client is None:
        # Offline mode gets a transport that raises on any request.
        transport = OfflineTransport() if params.get("offline") else None
        client = HttpxJiraClient(
            credentials,
            timeout=float(params.get("timeout") or 30.0),
            max_retries=int(params.get("max_retries") or 0),
            transport=transport,
        )
    try:
        if params.get("check"):
            return await _run_check(client)
        sources = tuple(params.get("sources") or ())
        if not sources:
            click.echo("error: no issue keys or JQL given", err=True)
            return EXIT_RUNTIME
        if params.get("offline"):
            if params.get("as_jql"):
                click.echo("error: --offline supports cached issue keys only", err=True)
                return EXIT_RUNTIME
            return await _run_offline(params, credentials, sources)
        return await _run_fetch(params, client, credentials, sources)
    except (AuthError, NotFoundError, DeprecatedEndpointError, JiraError) as exc:
        click.echo(f"error: {exc}", err=True)
        return exit_code_for(exc)
    finally:
        if owns_client:
            await client.aclose()


_PROG_NAME = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "jira2md"
if _PROG_NAME not in ("jira2md", "jira2md-api"):
    _PROG_NAME = "jira2md"


@click.command(name="jira2md")
@click.version_option(__version__, prog_name=_PROG_NAME)
@click.argument("sources", nargs=-1, metavar="KEY_OR_JQL")
@click.option(
    "-j",
    "--jql",
    "as_jql",
    is_flag=True,
    help="Treat SOURCES as JQL instead of issue keys",
)
@click.option("--fields", default=None, help="Comma-separated field allowlist")
@click.option("--history", is_flag=True, help="Include changelog")
@click.option(
    "--max-pages",
    default=200,
    show_default=True,
    help="Search pagination cap",
)
@click.option("--url", default=None, help="Jira base URL [env: JIRA_URL]")
@click.option("--email", default=None, help="Account email [env: JIRA_EMAIL]")
@click.option("--token", default=None, help="API token / PAT [env: JIRA_TOKEN]")
@click.option(
    "--auth",
    type=click.Choice(["basic", "bearer"]),
    default=None,
    help="Auth scheme (default: auto)",
)
@click.option(
    "--env-file",
    "env_file",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to a .env file [env: JIRA2MD_ENV_FILE]",
)
@click.option(
    "--deployment",
    type=click.Choice(["cloud", "dc"]),
    default=None,
    help="Deployment type (default: auto-detect)",
)
@click.option("--check", is_flag=True, help="Verify credentials and exit")
@click.option(
    "-t",
    "--template",
    "template",
    default=None,
    help="Template file (default issue.md.j2)",
)
@click.option(
    "--template-dir",
    "template_dirs",
    multiple=True,
    type=click.Path(file_okay=False),
    help="Extra template search path (repeatable)",
)
@click.option(
    "--var",
    "variables",
    multiple=True,
    help="Extra template variable KEY=VALUE (repeatable)",
)
@click.option(
    "--single",
    is_flag=True,
    help="Render all issues through single.md.j2",
)
@click.option("--index", is_flag=True, help="Also emit index.md")
@click.option(
    "--no-frontmatter",
    is_flag=True,
    help="Use a template variant without YAML front matter",
)
@click.option(
    "-o",
    "--out",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False),
    help="Output directory",
)
@click.option(
    "--stdout", "to_stdout", is_flag=True, help="Write to stdout instead of files"
)
@click.option(
    "--name-template",
    default="{{ issue.key }}.md",
    show_default=True,
    help="Filename pattern",
)
@click.option(
    "--assets-dir",
    default="assets",
    show_default=True,
    help="Attachment directory",
)
@click.option(
    "--no-assets",
    is_flag=True,
    help="Do not download attachments",
)
@click.option(
    "--cache-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Cache raw JSON responses",
)
@click.option(
    "--offline",
    is_flag=True,
    help="Render from cache only, no network",
)
@click.option(
    "--concurrency",
    default=4,
    show_default=True,
    help="Parallel issue fetches",
)
@click.option("--timeout", default=30.0, show_default=True, help="Request timeout (s)")
@click.option(
    "--max-retries",
    default=5,
    show_default=True,
    help="Retry budget for 429/5xx",
)
@click.option("-v", "--verbose", count=True, help="Verbose (-v) / debug (-vv)")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Fetch and render, write nothing",
)
def main(**params: Any) -> None:
    """Fetch Jira work items over REST API v2 and render them as Markdown.

    SOURCES are issue keys (e.g. ABC-123) or, with --jql, a JQL query.
    """
    _setup_logging(int(params.get("verbose") or 0))
    params["sources"] = tuple(params.get("sources") or ())
    try:
        exit_code = asyncio.run(run(params))
    except KeyboardInterrupt:
        click.echo("interrupted", err=True)
        sys.exit(EXIT_RUNTIME)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
