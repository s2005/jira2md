# Security policy

## Supported versions

Security fixes are applied to the latest published release. Upgrade to the
latest release before reporting a problem that may already be fixed.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed secret.
Use GitHub's private vulnerability reporting form:

<https://github.com/s2005/jira2md/security/advisories/new>

Include the affected version, a minimal reproduction, the expected impact,
and any suggested mitigation. Do not include working credentials or private
Jira content.

## Sensitive local data

The CLI does not write credentials to its cache metadata. Raw Jira payloads
may still contain confidential issue descriptions, comments, user details,
attachment URLs, or secrets entered by Jira users. Keep cache directories,
rendered output, and downloaded attachments private unless their contents
have been reviewed for publication.
