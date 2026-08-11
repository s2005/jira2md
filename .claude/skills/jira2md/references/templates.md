# jira2md template authoring

How to use and customize the Jinja2 templates that turn fetched issues into Markdown.

## Contents

- [Resolution order](#resolution-order)
- [Shipped templates](#shipped-templates)
- [Template context](#template-context)
- [Environment settings](#environment-settings)
- [Issue object reference](#issue-object-reference)
- [Custom filters](#custom-filters)
- [Tests](#tests)
- [Recipes](#recipes)
- [Behaviour notes](#behaviour-notes)

## Resolution order

Searched first to last; the first match wins:

1. `--template-dir DIR` paths, repeatable, in the order given
2. `.jira2md/templates/` in the current working directory
3. The templates shipped inside the package

Creating `.jira2md/templates/<name>` in a project overrides a shipped template without passing any flag.

## Shipped templates

| File | Renders | Triggered by |
| ---- | ------- | ------------ |
| `issue.md.j2` | One document per issue | default |
| `single.md.j2` | All issues combined into one document | `--single` |
| `index.md.j2` | A table of issues with links | `--index` |
| `release-notes.md.j2` | Issues grouped by fix version and type | `-t release-notes.md.j2` |

## Template context

| Variable | Present when | Content |
| -------- | ------------ | ------- |
| `issues` | Always | List of all normalised `Issue` objects |
| `issue` | Per-issue renders; also auto-set when `issues` holds exactly one | The normalised `Issue` |
| `raw` | Per-issue renders | Raw REST API v2 payload, full fidelity (for example `raw.changelog` under `--history`) |
| `base_url` | Always | Jira base URL |
| `now` | Always | UTC timestamp; pinned to the latest cache `fetched_at` on `--offline` runs |
| `config.frontmatter` | Always | False when `--no-frontmatter` |
| `config.assets_dir` | Always | The `--assets-dir` value, default `assets` |
| `--var KEY=VALUE` | When given | Extra top-level variables |

## Environment settings

`autoescape` off (the output is Markdown, and HTML escaping would corrupt it), `trim_blocks` and `lstrip_blocks` on, trailing newline kept, and `ChainableUndefined` as the undefined type. Missing fields therefore render empty instead of raising, so `issue.custom['customfield_10016']` is safe on issues that lack the field.

## Issue object reference

| Attribute | Type | Notes |
| --------- | ---- | ----- |
| `key`, `summary`, `issue_type`, `status` | str | Always present, possibly empty |
| `description` | str or None | Raw wiki markup; pipe through `wiki` |
| `priority`, `resolution` | str or None | |
| `assignee`, `reporter` | `User` or None | `display_name`, `account_id`, `email`, `raw` |
| `created`, `updated` | datetime | Timezone-aware; fall back to the epoch when unparseable |
| `resolved` | datetime or None | |
| `labels`, `components`, `fix_versions` | tuple[str] | |
| `parent` | `IssueRef` or None | `key`, `summary`, `status` |
| `subtasks` | tuple[`IssueRef`] | |
| `links` | tuple[`IssueLink`] | `link_type` (the directional name, e.g. "blocks"), `direction` (`inward`/`outward`), `target` (an `IssueRef`) |
| `attachments` | tuple[`Attachment`] | `filename`, `size`, `mime_type`, `content_url`, `author`, `created`, `path` |
| `comments` | tuple[`Comment`] | `id`, `body` (raw wiki markup), `author` (`User`), `created`, `updated`; sorted oldest first |
| `custom` | mapping | Every `customfield_*` value, keyed by its raw field ID |
| `url` | str | `{base_url}/browse/{key}` |
| `raw` | mapping | The full REST v2 payload |
| `frontmatter` | property, mapping | Key metadata; pipe through `yaml` |

Two details worth knowing:

- `issue.custom` keys are the raw IDs (`customfield_10016`), not human field names. The model supports a name map, but the CLI does not populate one. Find the ID once with `jira2md ABC-123 --stdout -t <tpl>` printing `raw.fields`, or in Jira's field administration.
- `attachment.path` is the render-time link target: `<assets-dir>/<KEY>/<stored-filename>` when downloads are on, or the remote Jira `content_url` under `--no-assets`. Colliding filenames within one issue get `-1`, `-2`, ... suffixes before the extension.

## Custom filters

| Filter | Purpose | Example |
| ------ | ------- | ------- |
| `wiki` | Jira wiki markup to Markdown; rewrites `!name!` image references to the current issue's attachment targets | `{{ issue.description \| wiki }}` |
| `adf` | Atlassian Document Format payload to Markdown | `{{ raw.fields.description \| adf }}` |
| `yaml` | Mapping to a YAML block, no `---` markers, key order preserved | `{{ issue.frontmatter \| yaml }}` |
| `slug` | Text to an ASCII, lowercase, hyphenated slug | `{{ issue.summary \| slug }}` |
| `isodate` | Datetime or Jira timestamp string to full ISO-8601 | `{{ c.created \| isodate }}` |
| `reldate` | Datetime to a human relative string ("3 days ago", "in 2 hours", "just now") | `{{ issue.updated \| reldate }}` |
| `indent_md(width=2)` | Indent every line by `width` spaces, leaving fenced code blocks and blank lines untouched | `{{ body \| indent_md(4) }}` |
| `heading(level=1)` | Renormalise existing Markdown heading lines to `level`; non-heading lines pass through unchanged | `{{ issue.description \| wiki \| heading(3) }}` |
| `jirauser` | `User`, raw user dict, or None to a plain display name, falling back to the account identifier | `{{ c.author \| jirauser }}` |

`heading` rewrites `#` markers, it does not add them: use it to flatten a converted description under a fixed level, not to turn plain text into a heading.

`reldate` defaults to the current time; pass the context clock for reproducible offline output: `{{ issue.updated | reldate(now=now) }}`.

## Tests

`is_epic` (issue type is Epic), `is_done` (a resolution is set, or the status is one of done/closed/resolved/complete), `has_attachments`.

```jinja
{% if issue is is_done %}Resolved: {{ issue.resolution }}{% endif %}
```

## Recipes

Minimal custom issue template (`my-tpl/issue.md.j2`):

```jinja
{% if config.frontmatter %}
---
{{ issue.frontmatter | yaml }}---
{% endif %}

# {{ issue.key }}: {{ issue.summary }}

**{{ issue.status }}** | {{ issue.issue_type }} | assignee: {{ issue.assignee.display_name if issue.assignee else "unassigned" }}

{{ issue.description | wiki }}

{% for c in issue.comments %}
> {{ c.author | jirauser }} ({{ c.created | isodate }}): {{ c.body | wiki | indent_md(2) }}
{% endfor %}
```

Use it:

```bash
jira2md ABC-123 --template-dir my-tpl --stdout      # quick check
jira2md ABC-123 --template-dir my-tpl -o out/       # write files
```

Reach anything the model does not expose through `raw`, the REST v2 payload:

```jinja
Estimate: {{ raw.fields.customfield_10016 }}
{% for h in raw.changelog %}
{{ h.created }}: {% for i in h.items %}{{ i.field }}: {{ i.fromString }} -> {{ i.toString }}; {% endfor %}
{% endfor %}
{# raw.changelog requires --history #}
```

Group issues in a multi-issue template, release-notes style:

```jinja
{% for version, vgroup in issues | groupby("fix_versions.0", default="Unscheduled") %}
## {{ version }}
{% for issue in vgroup %}
- {{ issue.key }} - {{ issue.summary }}
{% endfor %}
{% endfor %}
```

Iterate on a template with no network at all:

```bash
jira2md ABC-123 --cache-dir .jira2md/cache -o out/                      # fetch once
jira2md ABC-123 --cache-dir .jira2md/cache --offline --template-dir my-tpl --stdout
```

## Behaviour notes

- A template error, including a missing template file, exits with code 4.
- Missing fields never crash a template; `ChainableUndefined` renders them empty.
- CRLF in template sources is normalised to LF, so output stays byte-identical across platforms and across offline re-renders.
- `--single` always uses `single.md.j2` and ignores `-t`; `-t` picks the per-issue template otherwise. Output filenames come from `--name-template`, default `{{ issue.key }}.md`, which is itself rendered with `issue` in scope.
- `--no-frontmatter` reaches templates as `config.frontmatter`; the shipped templates gate their YAML block on it.
