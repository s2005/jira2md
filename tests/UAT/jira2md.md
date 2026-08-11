# UAT: `jira2md`

Manual user-acceptance test for `jira2md`: confirmation that the CLI
authenticates against a live Jira instance, renders a fixture issue to
Markdown with front matter and downloaded attachments, re-renders
byte-identically from its cache in offline mode, and maps each failure mode
to its own exit code (1 runtime, 2 authentication, 3 not found, 4 template).
The command reads from Jira and writes Markdown files under `uat-out/`, which
the cleanup section removes.

## Prerequisites

The shared setup in [README.md](README.md) - dependencies synced, credentials
exported, and the fixture issues created on the test instance: `UATMD-1` with
a rich-text description and at least one image attachment, and `UATMD-999`
absent. This guide needs nothing beyond that shared setup.

## What this uses

Credentials resolve from the environment the README setup exports; the guide
names no credential on any command line except the deliberately invalid token
of the authentication case.

| Flag / value | Why |
| ------------ | --- |
| `UATMD-1` | The primary fixture issue (see [README.md](README.md)) - fetched, rendered, cached |
| `UATMD-999` | A key that must not exist - the exit-3 not-found case |
| `--check` | Verifies credentials via `/rest/api/2/myself` and renders nothing |
| `--token uat-invalid-token` | Overrides the env token with a bad one - the exit-2 case |
| `--stdout` | Renders to the terminal instead of writing files |
| `-o uat-out/single` | Output directory for the file-render step |
| `--cache-dir uat-out/cache` | Caches the raw JSON payload plus a secret-free meta file |
| `--offline` | Renders from the cache only; any network attempt is an error |
| `--cache-dir uat-out/cache-empty` | A cache location holding nothing - the offline cache-miss case |
| `-t does-not-exist.md.j2` | A template that must not resolve - the exit-4 case |

## Run it

From the repo root, under Git Bash, with the README setup exported:

```bash
uv run jira2md UATMD-1 --stdout
```

## What to check

- The version prints and exits 0:

  ```bash
  uv run jira2md --version
  ```

  Output starts with `jira2md, version`.

- Valid credentials verify and exit 0:

  ```bash
  uv run jira2md --check
  ```

  Output is one line beginning with `Authenticated as`, followed by your Jira display name.

- Running with no issue keys and no JQL is a runtime error, exit 1:

  ```bash
  uv run jira2md
  ```

  Output is `error: no issue keys or JQL given`.

- An invalid token is an authentication error, exit 2:

  ```bash
  uv run jira2md --check --token uat-invalid-token
  ```

  Output starts with `error: Authentication failed`.

- A key that does not exist is a not-found error, exit 3:

  ```bash
  uv run jira2md UATMD-999
  ```

  Output starts with `error: Not found or no permission`.

- Offline mode without a cache directory is a runtime error, exit 1:

  ```bash
  uv run jira2md --offline UATMD-1
  ```

  Output is `error: --offline requires --cache-dir`.

- Offline mode with an empty cache is a runtime error, exit 1:

  ```bash
  uv run jira2md --offline --cache-dir uat-out/cache-empty UATMD-1
  ```

  Output is `error: no cached payload for UATMD-1`.

- The fixture issue renders to stdout, exit 0:

  ```bash
  uv run jira2md UATMD-1 --stdout
  ```

  Output starts with the YAML front matter delimiter `---` and carries the
  line `key: UATMD-1`.

- The fixture issue renders to a file with its attachments, exit 0:

  ```bash
  uv run jira2md UATMD-1 -o uat-out/single
  ```

  The file `uat-out/single/UATMD-1.md` exists and contains `key: UATMD-1`;
  the attachment the fixture carries landed under
  `uat-out/single/assets/UATMD-1/`, and the Markdown links it as
  `assets/UATMD-1/` rather than a Jira content URL.

- The offline re-render is byte-identical, exit 0. First populate the cache
  and an online rendering:

  ```bash
  uv run jira2md UATMD-1 --cache-dir uat-out/cache -o uat-out/online
  ```

  Then render offline from that cache:

  ```bash
  uv run jira2md --offline --cache-dir uat-out/cache -o uat-out/offline UATMD-1
  ```

  The cache directory holds `UATMD-1.json` plus a `UATMD-1_meta.json` whose
  keys are exactly `fetched_at`, `etag`, `fields`, `endpoint` - never a
  token - and `cmp uat-out/online/UATMD-1.md uat-out/offline/UATMD-1.md`
  reports no differences.

- A template that does not exist is a template error, exit 4:

  ```bash
  uv run jira2md UATMD-1 -t does-not-exist.md.j2 --stdout
  ```

  Output starts with `template error:`.

## Scripted equivalent

[`jira2md.sh`](jira2md.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above:

```bash
./jira2md.sh          # step through it, one keypress per step
./jira2md.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

- `tests/unit/test_cli.py` - exit-code mapping, cache/offline
  byte-parity, and secret hygiene against a mock transport.
- `tests/unit/test_client.py` - 401/404 mapping and retry behavior.
- `tests/integration/test_cassettes.py` - end-to-end rendering
  against recorded Cloud and Data Center responses.

## Cleanup

Remove exactly what this guide wrote:

```bash
rm -rf uat-out
```

`uat-out/` holds only this guide's output, cache, and downloaded fixtures.
The walkthrough script removes the same paths itself in its final step unless
run with `--keep-output`.
