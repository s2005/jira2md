"""Shared fixtures for the jira2md unit tests.

``resolve_credentials`` falls back to a ``.env`` file (working directory,
then the per-user location) and to ambient ``JIRA_*`` environment
variables. On a developer machine that has either of those, the values
leak into tests asserting on unconfigured behaviour, so every test in
this package runs against empty env-file locations with the ambient
variables removed.
"""

from __future__ import annotations

import pytest

from jira2md import config as jira2md_config

JIRA_ENV_VARS = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "JIRA_AUTH",
    "JIRA2MD_ENV_FILE",
)


@pytest.fixture(autouse=True)
def isolate_user_credentials(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolate credential resolution from the developer's own config."""
    empty = tmp_path_factory.mktemp("jira2md-config")
    monkeypatch.setattr(
        jira2md_config, "local_env_file_path", lambda: empty / "local.env"
    )
    monkeypatch.setattr(
        jira2md_config, "user_env_file_path", lambda: empty / "user.env"
    )
    for env_var in JIRA_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
