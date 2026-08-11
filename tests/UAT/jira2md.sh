#!/usr/bin/env bash
#
# jira2md.sh - guided, self-checking walkthrough of jira2md.md.
#
# Runs every check the guide describes for `jira2md`: each step explains
# what it exercises, echoes and runs the guide's exact command, shows the real
# output and the observed vs expected exit code, asserts the expectation, and
# waits for a keypress before the next step.
#
# Prerequisites - the shared setup in README.md:
#   uv sync --frozen --all-extras --dev
#   export JIRA_URL=... JIRA_EMAIL=... JIRA_TOKEN=...
#   fixture issues UATMD-1 (description + attachment) and UATMD-2 present,
#   UATMD-999 absent on the test instance
#
# Writes Markdown, cached JSON, and downloaded attachments under uat-out/.
# The final step removes exactly those paths unless --keep-output is given.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: steps 3-7 and 11 expect a non-zero exit code (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The values this guide names. Every one is synthetic and published in
# README.md - no real account, host, or credential. The real instance arrives
# through the environment or the --url / --email / --token / --key flags.
readonly BAD_TOKEN="uat-invalid-token"
readonly BAD_TEMPLATE="does-not-exist.md.j2"
readonly OUT_ROOT="uat-out"

STEP_TITLES=(
    "Preflight - uv, the CLI, credentials, and the fixture issue"
    "The version prints"
    "Valid credentials verify"
    "No keys and no JQL is a runtime error"
    "An invalid token is an authentication error"
    "A missing key is a not-found error"
    "Offline without a cache directory is refused"
    "Offline with an empty cache is a clean miss"
    "The fixture issue renders to stdout with front matter"
    "The fixture issue renders to a file with its attachment"
    "The offline re-render is byte-identical"
    "A missing template is a template error"
    "Cleanup removes exactly what this walkthrough wrote"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
jira2md.sh - guided walkthrough of jira2md.md

Usage:
  ./jira2md.sh [options]

Options:
  --auto, --no-pause     Run every step back-to-back with no keypress prompt
  --stop-on-fail         Abort at the first failed step (default: run them all)
  --from-step N          Start at step N, skipping the earlier ones
  --only-step N          Run exactly one step
  --list-steps           Print the step index and exit
  --url URL              Jira base URL (default: $JIRA_URL env, else the
                         synthetic value in README.md)
  --email EMAIL          Account email (default: $JIRA_EMAIL env)
  --token TOKEN          API token / PAT (default: $JIRA_TOKEN env)
  --key KEY              Primary fixture issue key (default: UATMD-1)
  --key-second KEY       Second fixture issue key (default: UATMD-2)
  --seed                 No-op: the Jira fixture is created by hand, see
                         README.md
  --cleanup              No-op: the walkthrough cleans its own files in the
                         final step
  --keep-output          Keep the files the run writes instead of deleting them
  --help                 Show this help and exit

Prerequisites: dependencies synced, credentials exported, and the fixture
issues present on the test instance (see README.md).

Cleanup: the final step removes exactly the files this walkthrough wrote under
uat-out/ unless --keep-output is given.
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "Everything below needs uv, the jira2md console script, working credentials, and the primary fixture issue. Checking all four once here turns a missing prerequisite into one clear message instead of a dozen confusing step failures."
    uat_expect "uv is on PATH, the CLI answers --version, --check exits 0, and a quiet render of $UAT_KEY succeeds. Anything missing exits 3 naming the fix."

    uat_require_cmd "uv" "Install uv, or run the suite from an environment that has it."
    uat_pass "uv is on PATH"

    uat_run_quiet "${UAT_BASE_CMD[@]}" --version
    if [[ "$UAT_RC" -ne 0 ]]; then
        printf '%s\n' "$UAT_OUT"
        uat_fatal "$UAT_EXIT_PREREQ" \
            "jira2md does not run (exit $UAT_RC). Fix with:
    uv sync --frozen --all-extras --dev"
    fi
    uat_pass "jira2md runs"

    uat_run_quiet "${UAT_BASE_CMD[@]}" --check
    if [[ "$UAT_RC" -ne 0 ]]; then
        printf '%s\n' "$UAT_OUT"
        uat_fatal "$UAT_EXIT_PREREQ" \
            "credentials do not verify (exit $UAT_RC). Fix with:
    export JIRA_URL=... JIRA_EMAIL=... JIRA_TOKEN=...
or pass --url / --email / --token (see README.md)."
    fi
    uat_pass "credentials verify against $JIRA_URL"

    uat_run_quiet "${UAT_BASE_CMD[@]}" "$UAT_KEY" --stdout --no-assets
    if [[ "$UAT_RC" -ne 0 ]]; then
        printf '%s\n' "$UAT_OUT"
        uat_fatal "$UAT_EXIT_PREREQ" \
            "fixture issue $UAT_KEY is not fetchable (exit $UAT_RC). Fix by creating it on the test instance; it needs a description and at least one attachment (see the README fixture table), or point the run at one with --key."
    fi
    uat_pass "fixture issue $UAT_KEY is fetchable"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "The entry point itself: the console script resolves and reports its version, which is also the cheapest proof the packaging entry point is wired."
    uat_expect "exit 0 and a line starting with 'jira2md, version'."

    uat_run 0 "${UAT_BASE_CMD[@]}" --version
    uat_assert_contains "jira2md, version" "the version line names the CLI"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "--check verifies credentials via /rest/api/2/myself and renders nothing - the operator's first command against a new instance."
    uat_expect "exit 0 and one line starting with 'Authenticated as '."

    uat_run 0 "${UAT_BASE_CMD[@]}" --check
    uat_assert_contains "Authenticated as " "the CLI names the authenticated account"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "The guide's invocation-error bullet: with no issue keys and no JQL the CLI must fail cleanly with the runtime exit code, not hang and not guess."
    uat_expect "exit 1 and 'error: no issue keys or JQL given'."

    uat_run 1 "${UAT_BASE_CMD[@]}"
    uat_assert_contains "error: no issue keys or JQL given" "the empty invocation is named"
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "The guide's authentication bullet: a bad token is exit 2, distinct from a lookup miss or a runtime error, so a script can tell 'fix the credentials' from every other failure."
    uat_expect "exit 2 and output starting with 'error: Authentication failed'."

    uat_run 2 "${UAT_BASE_CMD[@]}" --check --token "$BAD_TOKEN"
    uat_assert_contains "Authentication failed" "the 401 maps to the authentication error"
}

step_5() {
    uat_step 5 "${STEP_TITLES[5]}"
    uat_explain "The guide's not-found bullet: a key that does not exist on the instance is exit 3 with a clear message, not a crash and not a silent empty render."
    uat_expect "exit 3 and output starting with 'error: Not found or no permission'."

    uat_run 3 "${UAT_BASE_CMD[@]}" "$UAT_KEY_MISSING"
    uat_assert_contains "Not found or no permission" "the 404 maps to the not-found error"
}

step_6() {
    uat_step 6 "${STEP_TITLES[6]}"
    uat_explain "Offline mode is only meaningful against a cache; asking for it without --cache-dir is a usage problem the CLI refuses before touching the network."
    uat_expect "exit 1 and 'error: --offline requires --cache-dir'."

    uat_run 1 "${UAT_BASE_CMD[@]}" --offline "$UAT_KEY"
    uat_assert_contains "error: --offline requires --cache-dir" "offline without a cache dir is refused"
}

step_7() {
    uat_step 7 "${STEP_TITLES[7]}"
    uat_explain "The guide's cache-miss bullet: offline mode against a cache location holding nothing reports the miss per key and exits 1 - no network attempt, no fabricated output."
    uat_expect "exit 1 and 'error: no cached payload for $UAT_KEY'."

    uat_run 1 "${UAT_BASE_CMD[@]}" --offline --cache-dir "$OUT_ROOT/cache-empty" "$UAT_KEY"
    uat_assert_contains "error: no cached payload for $UAT_KEY" "the missing key is named"
}

step_8() {
    uat_step 8 "${STEP_TITLES[8]}"
    uat_explain "The core of the command: fetch the fixture issue over REST API v2 and render it as Markdown with YAML front matter, straight to the terminal."
    uat_expect "exit 0; output starts with '---' and carries the line 'key: $UAT_KEY'."

    uat_run 0 "${UAT_BASE_CMD[@]}" "$UAT_KEY" --stdout
    uat_assert_contains "---" "the front matter delimiter opens the document"
    uat_assert_contains "key: $UAT_KEY" "the front matter carries the issue key"
}

step_9() {
    uat_step 9 "${STEP_TITLES[9]}"
    uat_explain "The guide's file-render bullet: the same issue written to a directory, with its attachment downloaded and linked by local path instead of the Jira content URL."
    uat_expect "exit 0; $OUT_ROOT/single/$UAT_KEY.md exists and contains 'key: $UAT_KEY'; at least one file landed under $OUT_ROOT/single/assets/$UAT_KEY/; the Markdown links assets/$UAT_KEY/."

    uat_run 0 "${UAT_BASE_CMD[@]}" "$UAT_KEY" -o "$OUT_ROOT/single"
    uat_assert_file_exists "$OUT_ROOT/single/$UAT_KEY.md" "the rendered file exists"
    uat_assert_file_contains "$OUT_ROOT/single/$UAT_KEY.md" "key: $UAT_KEY" "the rendered file carries the front matter key"

    local attachment found=0
    for attachment in "$OUT_ROOT/single/assets/$UAT_KEY"/*; do
        [[ -f "$attachment" ]] && found=1 && break
    done
    if [[ "$found" -eq 1 ]]; then
        uat_pass "an attachment was downloaded under $OUT_ROOT/single/assets/$UAT_KEY/"
    else
        uat_fail "an attachment was downloaded under $OUT_ROOT/single/assets/$UAT_KEY/"
    fi
    uat_assert_file_contains "$OUT_ROOT/single/$UAT_KEY.md" "assets/$UAT_KEY/" "the Markdown links the local asset path"
}

step_10() {
    uat_step 10 "${STEP_TITLES[10]}"
    uat_explain "The guide's cache-and-offline bullet: a fetch caches the raw payload plus a secret-free meta file, and an offline re-render from that cache is byte-identical - the determinism the cache contract promises."
    uat_expect "the cache holds $UAT_KEY.json and a meta file whose keys are fetched_at, etag, fields, endpoint and never the token; the offline run exits 0 and cmp reports no differences against the online rendering."

    uat_run_quiet "${UAT_BASE_CMD[@]}" "$UAT_KEY" --cache-dir "$OUT_ROOT/cache" -o "$OUT_ROOT/online"
    if [[ "$UAT_RC" -ne 0 ]]; then
        uat_fail "the preparatory cached fetch succeeded (exit $UAT_RC): $UAT_OUT"
        return
    fi
    uat_pass "the preparatory cached fetch succeeded"

    local meta payload candidate
    meta=""
    payload=""
    for candidate in "$OUT_ROOT/cache"/*/"$UAT_KEY"_meta.json; do
        [[ -f "$candidate" ]] && meta="$candidate" && break
    done
    for candidate in "$OUT_ROOT/cache"/*/"$UAT_KEY.json"; do
        [[ -f "$candidate" ]] && payload="$candidate" && break
    done
    if [[ -z "$meta" || -z "$payload" ]]; then
        uat_fail "the cache holds $UAT_KEY.json and ${UAT_KEY}_meta.json"
        return
    fi
    uat_pass "the cache holds $payload and $meta"

    uat_assert_json_file "$meta" fetched_at etag fields endpoint
    if grep -qF -- "$UAT_JIRA_TOKEN" "$meta" 2>/dev/null; then
        uat_fail "the meta file never carries the token"
    else
        uat_pass "the meta file never carries the token"
    fi

    uat_run 0 "${UAT_BASE_CMD[@]}" --offline --cache-dir "$OUT_ROOT/cache" -o "$OUT_ROOT/offline" "$UAT_KEY"
    if cmp -s "$OUT_ROOT/online/$UAT_KEY.md" "$OUT_ROOT/offline/$UAT_KEY.md"; then
        uat_pass "the offline rendering is byte-identical to the online one"
    else
        uat_fail "the offline rendering is byte-identical to the online one"
    fi
}

step_11() {
    uat_step 11 "${STEP_TITLES[11]}"
    uat_explain "The guide's template bullet: a template name that resolves nowhere is exit 4 with a clear message - a broken --template-dir must never look like a Jira problem."
    uat_expect "exit 4 and output starting with 'template error:'."

    uat_run 4 "${UAT_BASE_CMD[@]}" "$UAT_KEY" -t "$BAD_TEMPLATE" --stdout
    uat_assert_contains "template error:" "the missing template is named in the error"
}

step_12() {
    uat_step 12 "${STEP_TITLES[12]}"
    uat_explain "The guide's cleanup section, as an ordinary step rather than a trap: remove exactly the files this walkthrough wrote. The guide shows rm -rf uat-out for hand runs; the script is more surgical."
    uat_expect "exit 0 and uat-out gone afterwards - unless --keep-output was given, which skips this step."

    if [[ "$UAT_KEEP_OUTPUT" -eq 1 ]]; then
        uat_skip "--keep-output was given, so the walkthrough keeps its files"
        return
    fi

    uat_run 0 rm -rf \
        "$OUT_ROOT/single/$UAT_KEY.md" \
        "$OUT_ROOT/single/assets/$UAT_KEY" \
        "$OUT_ROOT/online/$UAT_KEY.md" \
        "$OUT_ROOT/offline/$UAT_KEY.md"
    # Cache files live under a hostname subdirectory this walkthrough created;
    # remove the two exact payloads, then the directories only if now empty.
    rm -f "$OUT_ROOT/cache"/*/"$UAT_KEY.json" "$OUT_ROOT/cache"/*/"$UAT_KEY"_meta.json 2>/dev/null
    rmdir "$OUT_ROOT/cache"/* "$OUT_ROOT/cache" \
        "$OUT_ROOT/single/assets" "$OUT_ROOT/single" \
        "$OUT_ROOT/online" "$OUT_ROOT/offline" \
        "$OUT_ROOT/cache-empty" "$OUT_ROOT" 2>/dev/null

    if [[ -e "$OUT_ROOT" ]]; then
        uat_fail "uat-out is fully removed (leftovers remain - rerun with --keep-output to inspect)"
    else
        uat_pass "uat-out is fully removed"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    uat_init
    UAT_TOTAL_STEPS="$LAST_STEP"

    local arg
    for arg in "$@"; do
        if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
            usage
            exit "$UAT_EXIT_OK"
        fi
    done

    uat_parse_common_args "$@"
    if [[ ${#UAT_REST[@]} -gt 0 ]]; then
        uat_fatal "$UAT_EXIT_USAGE" "unknown argument: ${UAT_REST[0]} (see --help)"
    fi

    if [[ "$UAT_LIST_ONLY" -eq 1 ]]; then
        uat_list_steps "jira2md.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: jira2md"
    printf '  guide    : jira2md.md\n'
    printf '  jira url : %s\n' "$UAT_JIRA_URL"
    printf '  fixture  : %s (missing: %s)\n' "$UAT_KEY" "$UAT_KEY_MISSING"
    printf '  steps    : %s..%s of 0..%s\n' "$UAT_FIRST_STEP" "$UAT_LAST_STEP" "$LAST_STEP"

    [[ "$UAT_DO_SEED" -eq 1 ]] && uat_seed

    uat_run_steps

    [[ "$UAT_DO_CLEANUP" -eq 1 ]] && uat_cleanup

    uat_summary
}

main "$@"
