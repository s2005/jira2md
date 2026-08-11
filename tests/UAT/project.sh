#!/usr/bin/env bash
#
# project.sh - the project-specific half of the UAT harness for jira2md.
#
# common.sh sources this file when it exists; it is never executed directly and
# never sourced on its own. Everything here is this project's business: the
# Jira credentials every guide shares, the fixture issue keys, and the extra
# flags every guide accepts. common.sh stays project-agnostic so it can be
# copied between repositories unchanged - put the local detail here instead.
#
# The fixture issues live in a live Jira instance the operator points the suite
# at, so seeding is a manual act documented in README.md, not a scripted one:
# the common.sh no-op uat_seed / uat_cleanup stay in place on purpose.

# ---------------------------------------------------------------------------
# Shared fixture values
#
# Synthetic defaults only - every one is published in the README fixture table.
# Real values arrive through the environment the README's shared setup exports,
# or through the per-run flags below.
# ---------------------------------------------------------------------------

uat_project_defaults() {
    UAT_JIRA_URL="${JIRA_URL:-https://uat-jira.example.com}"
    UAT_JIRA_EMAIL="${JIRA_EMAIL:-uat-user@example.com}"
    UAT_JIRA_TOKEN="${JIRA_TOKEN:-uat-secret-token-000}"

    # The fixture issue keys. UAT_KEY must exist and carry a description plus
    # at least one attachment; UAT_KEY_SECOND must exist; UAT_KEY_MISSING must
    # NOT exist on the instance.
    UAT_KEY="${UAT_KEY:-UATMD-1}"
    UAT_KEY_SECOND="${UAT_KEY_SECOND:-UATMD-2}"
    UAT_KEY_MISSING="UATMD-999"

    # This project's Python is behind a launcher, so point the JSON assertion
    # helper at it.
    UAT_PYTHON_CMD=(uv run python)

    _uat_project_compose
}

# Recompose anything derived from a value a flag can change. Called from
# uat_project_defaults and again from uat_project_after_args, so the derived
# values always match the resolved flags.
#
# Credentials travel through the environment, never on the command line: the
# harness echoes every command it runs, and a token on an echoed command line
# is a token in the log.
_uat_project_compose() {
    export JIRA_URL="$UAT_JIRA_URL"
    export JIRA_EMAIL="$UAT_JIRA_EMAIL"
    export JIRA_TOKEN="$UAT_JIRA_TOKEN"
    # run-all.sh drives guides as child processes; exporting the fixture keys
    # is how a --key / --key-second override reaches them.
    export UAT_KEY UAT_KEY_SECOND
    UAT_BASE_CMD=(uv run jira2md)
}

# uat_project_parse_arg "$@"
# Per-run overrides for the credentials and the fixture keys.
uat_project_parse_arg() {
    case "$1" in
        --url)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--url needs a Jira base URL"
            UAT_JIRA_URL="$2"
            UAT_ARG_CONSUMED=2
            ;;
        --email)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--email needs an account email"
            UAT_JIRA_EMAIL="$2"
            UAT_ARG_CONSUMED=2
            ;;
        --token)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--token needs an API token or PAT"
            UAT_JIRA_TOKEN="$2"
            UAT_ARG_CONSUMED=2
            ;;
        --key)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--key needs an issue key"
            UAT_KEY="$2"
            UAT_ARG_CONSUMED=2
            ;;
        --key-second)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--key-second needs an issue key"
            UAT_KEY_SECOND="$2"
            UAT_ARG_CONSUMED=2
            ;;
    esac
}

# uat_project_after_args
# Called once every flag is parsed. Rebuild whatever depends on a flag value.
uat_project_after_args() {
    _uat_project_compose
}
