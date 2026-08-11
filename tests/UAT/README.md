# UAT suite: jira2md

Hand-run user-acceptance tests for the `jira2md` CLI. Each command gets a
pair of artifacts: a short markdown guide an operator runs by hand and
eyeballs, and a self-checking bash walkthrough that runs the guide's own
commands and asserts every expectation. They complement the automated suite
(`tests/unit/`, `tests/integration/`): the automated tests
prove the code against recorded responses, these guides prove it against a
live Jira instance.

## Guides

| Command | Guide | Script | Needs |
| ------- | ----- | ------ | ----- |
| `jira2md` | [jira2md.md](jira2md.md) | [jira2md.sh](jira2md.sh) | Shared setup below; fixture issues `UATMD-1` / `UATMD-2` on the test instance |

## Shared prerequisites

Once per session, from the repo root under Git Bash (or any POSIX shell):

```bash
uv sync --frozen --all-extras --dev
export JIRA_URL="https://uat-jira.example.com"
export JIRA_EMAIL="uat-user@example.com"
export JIRA_TOKEN="uat-secret-token-000"
export UAT_KEY="UATMD-1"
export UAT_KEY_SECOND="UATMD-2"
```

Replace the three credential values with those of the Jira test instance the
suite runs against, and the two keys with real fixture issues there (see the
fixture table for what each must carry). Every script also accepts `--url`,
`--email`, `--token`, `--key`, and `--key-second` flags in place of the
environment.

The fixture issues must be created by hand on the test instance - the suite
deliberately does not script writes into a shared Jira:

- `UATMD-1` - has a rich-text description and at least one image attachment.
- `UATMD-2` - any second existing issue.
- `UATMD-999` - must NOT exist on the instance (the not-found case).

Teardown: nothing to tear down - the guides only read from Jira; the local
files they write are removed by each script's cleanup step (or kept with
`--keep-output`).

## Scripted runs

A walkthrough prints, for every step: why the step exists, what to expect,
the guide's exact command, its real output, the observed vs expected exit
code, and one `[PASS]`/`[FAIL]` line per assertion. The summary at the end
carries the verdict.

```bash
cd tests/UAT
./jira2md.sh           # step through it, one keypress per step
./jira2md.sh --auto    # run it unattended and print a verdict
./run-all.sh --auto        # run the whole roster, one guide at a time
```

Shared flags every script accepts:

| Flag | Meaning |
| ---- | ------- |
| `--auto`, `--no-pause` | Run every step back-to-back with no keypress prompt |
| `--stop-on-fail` | Abort at the first failed step instead of continuing |
| `--from-step N` | Start at step `N` |
| `--only-step N` | Run exactly one step |
| `--list-steps` | Print the step index and exit |
| `--seed` | Run the shared fixture seed (no-op here: the fixture is manual) |
| `--cleanup` | Remove the fixture afterwards (no-op here) |
| `--keep-output` | Keep the files the run writes |
| `--help`, `-h` | Usage and exit 0 |

Script exit codes: `0` every assertion passed, `1` an assertion failed,
`2` bad invocation, `3` a missing prerequisite (the message names the fix),
`130` interrupted.

## Run one at a time

The guides share one fixture and nothing serializes them. Never run two
walkthroughs concurrently, and never alongside the automated integration
suite. `run-all.sh` enforces this for the roster by running strictly
sequentially.

## Skipped steps

A `[SKIP]` line means a step could not run - typically because the fixture
issue it needs does not exist on the test instance, so its probe failed. A
skip never changes the exit code, but it moves the step out of `steps run`
and qualifies the verdict as `RESULT: PASS (N step(s) skipped)`, so a run
that mostly did not happen cannot read as a clean pass.

## Fixture table

Every synthetic value the guides name, so "no real values in a guide" stays
checkable:

| Value | Meaning |
| ----- | ------- |
| `https://uat-jira.example.com` | Synthetic Jira base URL; replaced by the `JIRA_URL` env or `--url` |
| `uat-user@example.com` | Synthetic account email; replaced by `JIRA_EMAIL` or `--email` |
| `uat-secret-token-000` | Synthetic API token; replaced by `JIRA_TOKEN` or `--token` |
| `uat-invalid-token` | Deliberately invalid token for the exit-2 authentication case |
| `UATMD-1` | Primary fixture issue: description plus an image attachment (`UAT_KEY` / `--key`) |
| `UATMD-2` | Second fixture issue for multi-issue runs (`UAT_KEY_SECOND` / `--key-second`) |
| `UATMD-999` | Key that must not exist on the test instance |
| `does-not-exist.md.j2` | Template name that must not resolve, for the exit-4 case |
| `uat-out/` | Output directory the guides write into and clean up |

## Adding a guide

1. Write `<command>.md` first, completely: no placeholders, synthetic values
   only, concrete expectations, and the failure modes with their exit codes.
2. Transcribe it into `<command>.sh`: one step per check bullet, step 0 the
   preflight, `common.sh` sourced once, no `set -e`.
3. Add a row to the guide table above and to the `ROSTER` in `run-all.sh`.
4. Record the exec bit: `git update-index --chmod=+x tests/UAT/<command>.sh`.
5. Run `./<command>.sh --auto` and make the verdict match the guide.
