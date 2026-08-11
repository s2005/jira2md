# JQL for jira2md

`-j/--jql` treats SOURCES as a JQL query and hands it to Jira's search endpoint verbatim. jira2md does not parse or validate the query, so anything the target instance supports works, and an invalid query fails server-side with exit 1.

Multiple SOURCES are joined with spaces, so quoting the whole query is the safe form:

```bash
jira2md -j "project = ABC and status = Done" -o out/
```

## Contents

- [Who: author, reporter, assignee](#who-author-reporter-assignee)
- [When: dates](#when-dates)
- [State and categorisation](#state-and-categorisation)
- [Operators](#operators)
- [Ready-made filters](#ready-made-filters)
- [Pagination](#pagination)
- [Official references](#official-references)

## Who: author, reporter, assignee

There is no single `author` field; pick the role actually meant.

| Field | Meaning | Examples |
| ----- | ------- | -------- |
| `reporter` | Who raised the ticket - usually what "author" means | `reporter = currentUser()`, `reporter = jdoe` |
| `creator` | The account that literally created it; differs when raised via automation or the API on someone's behalf | `creator = jdoe` |
| `assignee` | Who is currently responsible | `assignee = currentUser()`, `assignee is empty` |

## When: dates

All accept `"YYYY-MM-DD"`, relative values such as `-30d`, or functions such as `startOfDay()`.

| Field | Meaning | Examples |
| ----- | ------- | -------- |
| `created` | When the ticket was created | `created >= -30d`, `created > "2026-01-01"` |
| `updated` | Last time any field changed | `updated >= startOfWeek()` |
| `resolved` / `resolutiondate` | When it was resolved | `resolved >= -7d` |
| `dueDate` | Scheduled due date | `dueDate < endOfMonth()` |

## State and categorisation

| Field | Meaning | Examples |
| ----- | ------- | -------- |
| `project` | Project key | `project = ABC`, `project in (ABC, DEF)` |
| `status` | Workflow state, instance-specific | `status = Done`, `status != Closed`, `status was "In Progress"` |
| `issuetype` | Bug, Story, Task, Epic, ... | `issuetype = Bug`, `issuetype in (Story, Task)` |
| `priority` | Urgency level | `priority >= High`, `priority in (Highest, High)` |
| `resolution` | Why it was closed; empty means still open | `resolution = Done`, `resolution is empty` |
| `fixVersion` / `affectedVersion` | Version fixed in / broken by | `fixVersion = "2.0"`, `fixVersion in unreleasedVersions()` |
| `labels` / `component` | Tags / functional area | `labels = api`, `component = backend` |
| `text` / `summary` / `description` / `comment` | Free-text search | `text ~ "login error"` |
| `key` | Specific issue keys | `key in (ABC-1, ABC-2)` |
| Custom fields, quoted by name | Any instance custom field | `"Epic Link" = ABC-10`, `sprint in openSprints()` |

## Operators

`=` `!=` `>` `>=` `<` `<=` `~` `!~` `in` `not in` `is empty` `is not empty` `was` `was not` `was in` `was not in` `changed`.

Combine with `and` / `or` / `not`, quote values containing spaces, and sort with `ORDER BY field [ASC|DESC]`. Relative dates: `-30d`, `startOfDay()`, `endOfMonth()`.

## Ready-made filters

```text
reporter = currentUser() and created >= -30d and status != Done
status = Done and resolved >= startOfMonth() order by resolved DESC
assignee is empty and priority in (Highest, High)
project = ABC and fixVersion = "2.0" and resolution is not empty
project = ABC and updated >= -7d order by updated DESC
```

Applied:

```bash
jira2md -j "status = Done and resolved >= startOfMonth() order by resolved DESC" \
    -t release-notes.md.j2 -o release/
```

## Pagination

Cloud pages through `/search/jql` with `nextPageToken`; Server/Data Center uses `POST /search` with `startAt`. Both stop at `--max-pages` (default 200). Raise it for large result sets, or narrow the query.

## Official references

- Cloud: [JQL fields](https://support.atlassian.com/jira-software-cloud/docs/advanced-search-reference-jql-fields/) and [JQL operators](https://support.atlassian.com/jira-software-cloud/docs/advanced-search-reference-jql-operators/)
- Data Center: [advanced searching](https://confluence.atlassian.com/jirasoftwareserver/advanced-searching-939938733.html)
