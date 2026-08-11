"""jira2md: fetch Jira work items and render them as Markdown.

Public surface of the package. Everything the CLI and downstream
callers need is re-exported here; the submodules stay free of
cross-imports beyond this package.
"""

from jira2md.assets import (
    apply_attachment_paths,
    download_attachments,
)
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
    PaginationError,
)
from jira2md.config import (
    ConfigError,
    Credentials,
    resolve_credentials,
)
from jira2md.detect import detect_deployment
from jira2md.markup.adf import adf_to_md
from jira2md.markup.wiki import wiki_to_md
from jira2md.model import (
    Attachment,
    Comment,
    Issue,
    IssueLink,
    IssueRef,
    User,
)
from jira2md.render import build_environment, render

__all__ = [
    "DEFAULT_FIELDS",
    "Attachment",
    "AuthError",
    "Comment",
    "ConfigError",
    "Credentials",
    "DeprecatedEndpointError",
    "HttpxJiraClient",
    "Issue",
    "IssueLink",
    "IssueRef",
    "JiraClient",
    "JiraError",
    "NotFoundError",
    "OfflineTransport",
    "PaginationError",
    "User",
    "adf_to_md",
    "apply_attachment_paths",
    "build_environment",
    "detect_deployment",
    "download_attachments",
    "read_issue_cache",
    "render",
    "resolve_credentials",
    "wiki_to_md",
    "write_issue_cache",
]
