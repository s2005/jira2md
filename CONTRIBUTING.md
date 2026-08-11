# Contributing

Thank you for improving jira2md.

## Development setup

Use `uv` for all Python environment and package operations:

```bash
uv sync --all-extras --dev
pre-commit install
```

Create a feature or fix branch; do not work directly on `main`.

## Required checks

Run the same checks used by continuous integration before opening a pull
request:

```bash
uv lock --check
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q --integration
uv run ruff check .
uv run ruff format --check .
uv run mypy src
npx markdownlint-cli2
uv build
```

New features require tests. Bug fixes require a regression test. Preserve
byte-exact golden fixtures unless a verified rendering change requires them
to be regenerated.

## Security and private data

Never commit credentials, `.env` files, Jira cache data, rendered private Jira
content, or downloaded attachments. Follow [SECURITY.md](SECURITY.md) for
private vulnerability reports.

## Commits and pull requests

Use a conventional commit type such as `feat`, `fix`, `docs`, `test`, `ci`, or
`chore`. Include an appropriate attribution trailer and do not mention tools
in commit messages. Keep each pull request focused and describe how it was
verified.
