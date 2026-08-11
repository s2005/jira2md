"""Jinja2 rendering for jira2md.

``render`` is pure: given issues, a template name, and a context it
returns the rendered string. Template lookup honours three override
levels, searched in order: ``--template-dir`` paths, the per-project
``.jira2md/templates/`` directory, then the shipped package templates.

``autoescape`` is deliberately disabled -- the output is Markdown, and
HTML escaping would corrupt it. ``ChainableUndefined`` lets templates
reference missing fields (``issue.custom.Epic Link``) and render empty
instead of crashing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jinja2 import (
    ChainableUndefined,
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    PackageLoader,
)
from jinja2.loaders import BaseLoader

from jira2md.filters import FILTERS, TESTS

PROJECT_TEMPLATE_DIR = Path(".jira2md") / "templates"


class _NormalizingLoader(BaseLoader):
    """Wraps a loader and normalises CRLF template sources to LF.

    Shipped templates may be checked out with CRLF line endings on
    Windows; normalising keeps rendered output byte-identical across
    platforms and runs.
    """

    def __init__(self, inner: BaseLoader) -> None:
        self._inner = inner

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, Any]:
        source, filename, uptodate = self._inner.get_source(environment, template)
        return source.replace("\r\n", "\n"), filename, uptodate


def build_environment(
    template_dirs: Sequence[str | Path] = (),
) -> Environment:
    """Build the template Environment.

    Args:
        template_dirs: Extra directories searched before the shipped
            templates (``--template-dir`` values).

    Returns:
        A configured Jinja2 Environment.
    """
    loaders: list[BaseLoader] = [
        FileSystemLoader([str(path) for path in template_dirs])
    ]
    if PROJECT_TEMPLATE_DIR.is_dir():
        loaders.append(FileSystemLoader(str(PROJECT_TEMPLATE_DIR)))
    loaders.append(PackageLoader("jira2md", "templates"))

    environment = Environment(
        loader=_NormalizingLoader(ChoiceLoader(loaders)),
        # Markdown output, not HTML; escaping would corrupt it.
        autoescape=False,  # noqa: S701
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=ChainableUndefined,
    )
    environment.filters.update(FILTERS)
    environment.tests.update(TESTS)
    return environment


def render(
    issues: Sequence[Any],
    template: str,
    context: Mapping[str, Any],
    *,
    template_dirs: Sequence[str | Path] = (),
    environment: Environment | None = None,
) -> str:
    """Render a template against the given context.

    Args:
        issues: Normalised issues; exposed as ``issues`` and, for a
            single-issue run, as ``issue`` by the caller.
        template: Template file name (e.g. ``issue.md.j2``).
        context: Template context variables.
        template_dirs: Override directories searched first.
        environment: Pre-built Environment (tests); built when absent.

    Returns:
        The rendered Markdown string.
    """
    env = environment or build_environment(template_dirs)
    payload: dict[str, Any] = dict(context)
    payload.setdefault("issues", list(issues))
    if "issue" not in payload and len(payload["issues"]) == 1:
        payload["issue"] = payload["issues"][0]
    return env.get_template(template).render(**payload)
