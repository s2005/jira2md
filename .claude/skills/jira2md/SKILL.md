---
name: jira2md
description: Convert Jira work items to Markdown with the jira2md CLI. Use when asked to export, fetch, or download Jira issues as Markdown, run a JQL search to Markdown, generate release notes from Jira, re-render cached issues offline, or author and customize jira2md Jinja2 templates (.md.j2).
---

# jira2md

## Overview

`jira2md` is a fetch-only CLI. It downloads Jira work items over REST API v2 and renders them as Markdown through Jinja2 templates. It never writes to Jira: every request is a GET or a search POST.

Invocation:

- Installed globally (`uv tool install --force .` from a checkout): `jira2md`
- From a checkout without installing: `uv run jira2md`

`jira2md-api` is an alias of the same command. Confirm the binary with `jira2md --version`.

## Credentials

Resolution order, first hit wins per value: flags -> environment variables -> `.env` file.

| Flag | Env var / `.env` key |
| ---- | -------------------- |
| `--url` | `JIRA_URL` |
| `--email` | `JIRA_EMAIL` |
| `--token` | `JIRA_TOKEN` |
| `--auth basic\|bearer` | `JIRA_AUTH` |

- `.env` path: `--env-file` or `JIRA2MD_ENV_FILE`, else `./.env`, else `~/.config/jira2md/.env` (`%APPDATA%/jira2md/.env` on Windows). The first existing file wins; files are never merged. An explicitly given path that does not exist is an error.
- Cloud uses basic auth (account email + API token). Server/Data Center uses a personal access token as bearer; leave the email unset or pass `--auth bearer`.
- Auto-detection: email present -> basic, otherwise bearer.
- See `.env.example` in the repository root for the file format.

Always verify credentials before a real run:

```bash
jira2md --check          # exit 0 and "Authenticated as <name>" on success
```

## Core commands

```bash
# One <KEY>.md per issue
jira2md ABC-123 DEF-456 -o out/

# JQL search (SOURCES become the query with -j/--jql)
jira2md -j "project = ABC and fixVersion = 2.0" -o out/

# Release notes grouped by fix version and type
jira2md -j "project = ABC" -t release-notes.md.j2 -o release/

# One combined single.md plus an index.md
jira2md ABC-123 DEF-456 --single --index -o out/

# Print to the terminal, write nothing
jira2md ABC-123 --stdout

# Fetch and render, write nothing (no files, no cache)
jira2md ABC-123 --dry-run
```

## Key options

| Option | Effect |
| ------ | ------ |
| `-j/--jql` | Treat SOURCES as JQL (Cloud: `/search/jql` + `nextPageToken`; Server/DC: `POST /search` + `startAt`) |
| `-t/--template NAME` | Per-issue template, default `issue.md.j2` |
| `--template-dir DIR` | Extra template search path (repeatable) |
| `--var KEY=VALUE` | Extra top-level template variable (repeatable) |
| `--single` / `--index` | Render through `single.md.j2` / also emit `index.md` |
| `--no-frontmatter` | Skip the YAML front matter block |
| `-o/--out DIR` | Output directory (default `.`) |
| `--stdout` | Write Markdown to stdout instead of files |
| `--name-template` | Filename pattern, default `{{ issue.key }}.md` |
| `--assets-dir DIR` / `--no-assets` | Attachment directory (default `assets`) / skip downloads |
| `--cache-dir DIR` | Store raw JSON responses; see Cache below |
| `--offline` | Render from cache only, zero network; see Cache below |
| `--fields CSV` | Field allowlist |
| `--history` | Include the changelog (exposed to templates as `raw.changelog`) |
| `--max-pages N` | Search pagination cap (default 200) |
| `--concurrency N` | Parallel issue fetches (default 4) |
| `--timeout S` / `--max-retries N` | 30 s / 5 retries on 429 and 5xx |
| `--deployment cloud\|dc` | Skip deployment auto-detection |
| `--check` | Verify credentials and exit, fetch nothing |
| `-v` / `-vv` | Info / debug logging to stderr; the token is never logged |

Full list: `jira2md --help`.

## Cache and offline mode

`--cache-dir` and `--offline` separate fetching from rendering: fetch once, render many times, reproducibly.

- `--cache-dir DIR` stores each raw response as `<cache-dir>/<host>/<KEY>.json`, with `<KEY>_meta.json` beside it holding an allowlisted fetch record (timestamp, ETag, field list, endpoint). Credentials are never written.
- `--offline` makes zero network calls (the transport raises on any request) and renders exclusively from the cache. It requires `--cache-dir`, accepts issue keys only (not JQL), and fails cleanly on a cache miss: exit 1, `no cached payload for <KEY>`, nothing written.

```bash
jira2md ABC-123 --cache-dir .jira2md/cache -o out/                # fetch once
jira2md ABC-123 --cache-dir .jira2md/cache --offline -o out2/     # byte-identical, no network
jira2md ABC-123 --cache-dir .jira2md/cache --offline -t my.md.j2  # iterate on templates freely
```

Why it matters: template iteration without a Jira round-trip or rate limits; deterministic output (`now` is pinned to the cache's `fetched_at` in offline runs, so timestamps do not drift); and rendering in environments that must not hold Jira credentials. Credentials are excluded from cache metadata, but the raw Jira payload is not sanitised and may contain confidential information. Keep caches private and out of version control.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success |
| 1 | Runtime error (network, bad input, offline cache miss, empty JQL) |
| 2 | Authentication failure |
| 3 | Issue or resource not found |
| 4 | Template error, including a missing template file |
| 5 | Deprecated endpoint (HTTP 410) |

Assert outcomes with `$?` (POSIX shells) or `$LASTEXITCODE` (PowerShell).

## Attachments

Attachments download into `<out>/assets/<KEY>/` and `!name!` wiki references are rewritten to those local paths, for example `![](assets/ABC-123/diagram.png)`. `--no-assets` keeps the remote Jira content URLs and skips the downloads.

## Templates

Templates resolve in order: `--template-dir` paths -> `./.jira2md/templates/` -> the shipped set (`issue.md.j2`, `single.md.j2`, `index.md.j2`, `release-notes.md.j2`). Missing fields render empty instead of raising. Quick override check:

```bash
mkdir -p tpl && printf 'OVERRIDE {{ issue.key }}: {{ issue.summary }}\n' > tpl/issue.md.j2
jira2md ABC-123 --template-dir tpl --stdout
```

For template authoring - context variables, the `Issue` object reference, custom filters (`wiki`, `adf`, `yaml`, `slug`, `isodate`, `reldate`, `indent_md`, `heading`, `jirauser`), tests, and recipes - read [references/templates.md](references/templates.md).

## JQL

`-j` passes the query to Jira verbatim; jira2md neither parses nor validates it, so any field and syntax the instance supports works, and invalid JQL fails server-side with exit 1. For a field-by-field reference (who/when/state), operators, and ready-made filters, read [references/jql.md](references/jql.md).

## Gotchas

- Deployment type is auto-detected; override with `--deployment` only when detection is wrong or must be skipped.
- `--single` always renders through `single.md.j2` and ignores `-t`; `-t` selects the per-issue template otherwise.
- `--stdout` and `--dry-run` skip attachment downloads, but link rewriting still happens, so emitted `assets/...` paths point at files that were not written. Use `--no-assets` to keep remote URLs in that case.
- `--history` is required for changelog data. Comment lists that the issue payload truncates are re-fetched in full automatically, so no flag is needed for long comment threads.
- `issue.custom` is keyed by raw field IDs (`customfield_10016`), not human field names.
- Cache files and debug logs contain no secrets.
