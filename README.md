# jira2md

[![CI](https://github.com/s2005/jira2md/actions/workflows/ci.yml/badge.svg)](https://github.com/s2005/jira2md/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/s2005/jira2md)](https://github.com/s2005/jira2md/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A standalone, fetch-only CLI that downloads Jira work items over REST API v2 and renders them as Markdown through Jinja2 templates. It never writes to Jira.

## Install

Install globally with `uv` from a checkout of this repository:

```bash
uv tool install --force .
```

Or install the current public release directly from GitHub:

```bash
uv tool install git+https://github.com/s2005/jira2md.git@v0.1.0
```

Two console scripts are installed and are the same command: `jira2md` and its alias `jira2md-api`.

For development inside the checkout instead:

```bash
uv sync --all-extras --dev
uv run jira2md --help
```

## Configure

Credentials resolve in this order, first hit wins:

1. CLI flags: `--url`, `--email`, `--token`, `--auth`
2. Environment: `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, `JIRA_AUTH`
3. A `.env` file using those same `JIRA_*` names

The `.env` file is `--env-file <path>` (or `JIRA2MD_ENV_FILE`) when given, otherwise `./.env`, otherwise `~/.config/jira2md/.env` (`%APPDATA%/jira2md/.env` on Windows). The first of those that exists wins (files are not merged), and a path given explicitly must exist or the run fails.

Cloud uses basic auth (account email plus API token). Server/Data Center uses a personal access token as a bearer token; leave the email unset and the scheme is detected automatically. See [.env.example](.env.example) for the file format and the full variable list.

Verify a configuration without fetching anything:

```bash
jira2md --check
```

## Usage

```bash
jira2md ABC-123 DEF-456                      # one Markdown file per issue
jira2md -j "project = ABC and fixVersion = 2.0" \
    --template release-notes.md.j2 -o release/
jira2md ABC-123 --cache-dir .jira2md/cache           # fetch and cache raw responses
jira2md ABC-123 --cache-dir .jira2md/cache --offline # re-render, zero network
jira2md ABC-123 --stdout                     # write to stdout instead of files
```

Run `jira2md --help` for the full option list.

### Behaviour

- JQL search uses `/search/jql` with `nextPageToken` on Cloud, and `POST /search` with `startAt` on Server/Data Center.
- Attachments download into `<out>/assets/<KEY>/` and `!name!` references are rewritten to point at them; `--no-assets` keeps the remote URLs.
- `--cache-dir` stores raw responses; credentials are excluded from cache metadata, but issue content is not sanitised and may be confidential. Keep the cache private and out of version control. `--offline` re-renders from that cache byte-identically with no network access.
- Rich text is converted from both Jira wiki markup (Server/DC) and ADF (Cloud).

### Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success |
| 1 | Runtime error |
| 2 | Authentication failure |
| 3 | Issue or resource not found |
| 4 | Template error |
| 5 | API deprecation (410 Gone) |

## Templates

Template names resolve through three search levels, in order:

1. Any `--template-dir` path (repeatable)
2. The per-project `.jira2md/templates/` directory
3. The templates shipped inside the package

The shipped set is:

| Template | Purpose |
| -------- | ------- |
| `issue.md.j2` | One file per issue, with YAML front matter |
| `single.md.j2` | All issues concatenated into one document (`--single`) |
| `index.md.j2` | An index of the rendered issues (`--index`) |
| `release-notes.md.j2` | Issues grouped as release notes |

### Authoring a template

Drop a `.md.j2` file into `.jira2md/templates/` (or a `--template-dir`) and select it with `--template`. A same-named file at a higher search level shadows the shipped one, so `issue.md.j2` can be overridden wholesale.

The context carries `issue` (for a single-issue render), `issues`, and any `--var KEY=VALUE` pairs. Undefined attributes render empty rather than raising, so `{{ issue.custom['Epic Link'] }}` is safe on issues that lack the field.

Autoescaping is off, because the output is Markdown and HTML escaping would corrupt it.

## Development

```bash
uv sync --all-extras --dev
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q --integration
uv run pre-commit run --all-files
```

The hand-run acceptance suite lives in [tests/UAT](tests/UAT/README.md) and needs a live Jira instance.

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a change. Report security problems privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Not an official Atlassian product.
