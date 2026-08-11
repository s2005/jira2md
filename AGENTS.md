# jira2md

> **Audience**: LLM-driven engineering agents

---

## Repository map

| Path | Purpose |
| ---- | ------- |
| `src/jira2md/` | Library and CLI source (Python >= 3.10) |
| `src/jira2md/cli.py` | Click CLI, orchestration, exit-code mapping |
| `src/jira2md/client.py` | httpx Jira REST client, retry/backoff, pagers |
| `src/jira2md/config.py` | Credential resolution (flags, env vars, `.env` file) |
| `src/jira2md/detect.py` | Cloud vs Server/DC deployment detection |
| `src/jira2md/model.py` | Frozen dataclasses (`Issue`, `Attachment`, `User`, ...) |
| `src/jira2md/render.py` | Jinja2 environment construction and rendering |
| `src/jira2md/filters.py` | Jinja2 filters and tests |
| `src/jira2md/assets.py` | Attachment download and link rewriting |
| `src/jira2md/cache.py` | On-disk issue cache for offline replay |
| `src/jira2md/markup/wiki.py` | Jira wiki markup to Markdown |
| `src/jira2md/markup/adf.py` | ADF document walker to Markdown |
| `src/jira2md/templates/` | Shipped `.j2` templates, packaged as package data |
| `.claude/skills/jira2md/` | Project-scoped skill documenting the CLI for agents working in a checkout |
| `tests/unit/` | Unit suite plus golden-file fixtures |
| `tests/integration/` | Cassette replay suite, gated behind `--integration` |
| `tests/UAT/` | Hand-run acceptance guides against a live Jira |

---

## Architecture

- **Fetch-only.** Nothing in this package writes to Jira. Every request is a GET or a search POST.
- **Pure rendering.** `render()` takes issues, a template name, and a context, and returns a string. The CLI owns all I/O.
- **Deployment split.** Cloud and Server/DC differ in search endpoint, pagination, rich-text format (ADF vs wiki markup), and auth scheme. `detect.py` resolves which one is in play; check it before assuming behaviour.
- **Version.** `uv-dynamic-versioning` derives the version from the git tag. `cli.py` and `client.py` both read it back via `version("jira2md")` and fall back to `0.0.0`, which means a wrong distribution name degrades silently.

---

## Dev workflow

```bash
uv sync --all-extras --dev            # install dependencies
pre-commit install                    # setup hooks
uv run pytest tests/unit/ -q          # unit suite
uv run pytest tests/integration/ -q --integration   # cassette suite
uv run pre-commit run --all-files     # ruff + mypy + whitespace hooks
uv run pytest --cov=src/jira2md --cov-report=term-missing
```

Tests must pass and lint/typing must be clean before committing.

---

## Rules

1. **Package management**: ONLY use `uv`, NEVER `pip`
2. **Branching**: NEVER work on `main`, always create feature branches
3. **Type safety**: All functions require type hints
4. **Testing**: New features need tests, bug fixes need regression tests
5. **Commits**: Use trailers for attribution, never mention tools/AI
6. **Commit types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci` - scopes: `cli`, `client`, `render`, `markup`, `config`, `docs`
7. **File hygiene**: Prefer editing existing files over creating new ones

---

## Code conventions

- **Language**: Python >= 3.10
- **Line length**: 88 characters maximum
- **Imports**: Absolute imports, sorted by Ruff
- **Naming**: `snake_case` functions, `PascalCase` classes
- **Docstrings**: Google-style for all public APIs
- **Error handling**: Specific exceptions only
- **No Unicode in source**: keep source ASCII so Windows consoles do not raise `UnicodeEncodeError`

---

## Gotchas

- **Golden files are byte-parity fixtures.** `tests/unit/golden/*.md` are excluded from the `trailing-whitespace` and `end-of-file-fixer` hooks and pinned to LF by `.gitattributes`. Never let a formatter touch them; if output changes, regenerate deliberately.
- **Tag before building.** `uv tool install` on an untagged tree stamps `fallback-version = "0.0.0"`, and both runtime version lookups then report `0.0.0` without erroring.
- **Templates are package data.** They are force-included into the wheel. Verify template changes against the *installed* package, not just the source tree.
- **`--integration` is required** for the cassette suite; without it those tests are skipped, not failed.
- **CRLF on Windows.** `.gitattributes` pins golden files, cassettes, and templates to LF. `render.py` additionally normalises CRLF template sources so output stays identical across platforms.

---

## Quick reference

```bash
jira2md --check                        # verify credentials, fetch nothing
jira2md ABC-123 --stdout               # render one issue to stdout
jira2md ABC-123 --cache-dir .jira2md/cache     # fetch and cache raw responses
jira2md ABC-123 --cache-dir .jira2md/cache --offline   # re-render, zero network

git checkout -b feature/description    # New feature
git checkout -b fix/issue-description  # Bug fix
```
