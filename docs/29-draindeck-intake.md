# Draindeck Intake v1

**Status:** Implemented under accepted ADR-28 on 2026-08-29. This document
describes the optional `draindeck_intake` package only. Doc 03, `src/runtime`,
Dashboard ownership, event schemas, and Git/recovery behavior are unchanged.

## Purpose and boundary

Intake is an explicit one-way preflight compiler:

```text
local Issues.md | GitHub | Jira Cloud | Linear
                    -> CanonicalIssueV1
                    -> managed Issues.md
                    -> operator inspection
                    -> existing Draindeck run (separate command)
```

It owns no workflow state and performs no synchronization. It does not open an
event log, import runtime events, invoke Git, call an engine/reviewer, start a
daemon, write provider data, or alter an issue already represented in the
event log. The generated file remains input; after ingestion, the event log is
the sole workflow authority.

## Commands

Run after installing Draindeck itself:

```powershell
draindeck-intake sync issues-md `
  --input C:\source\Issues.md `
  --output C:\target\Issues.md

draindeck-intake sync github `
  --owner OWNER --repo REPO `
  --output C:\target\Issues.md

draindeck-intake sync jira `
  --base-url https://SITE.atlassian.net `
  --jql "project = KEY ORDER BY created ASC" `
  --output C:\target\Issues.md

draindeck-intake sync linear `
  --team-key ENG `
  --output C:\target\Issues.md
```

All providers accept `--id-prefix`, `--page-size` (1–100), `--max-issues`
(1–100,000), `--timeout-seconds` (>0–300), `--output`, and `--force`.
`issues-md` defaults to unchanged IDs; GitHub, Jira, and Linear default to
`gh`, `jira`, and `linear` prefixes.

### Credentials

| Source | Default environment variables | CLI name override |
|---|---|---|
| GitHub | optional `GITHUB_TOKEN` | `--token-env NAME` |
| Jira Cloud | required `JIRA_EMAIL`, `JIRA_API_TOKEN` | `--email-env NAME`, `--token-env NAME` |
| Linear | required `LINEAR_API_KEY` | `--key-env NAME` |

Only environment-variable names are accepted on the command line. Secret
values are resolved in memory, never included in success/error JSON, and never
written to generated output. Jira uses email plus API token for Basic auth;
Linear personal API keys use the documented raw `Authorization` value.

## Canonical and generated contracts

Every provider record must construct immutable `CanonicalIssueV1`:

- ID grammar: `[A-Za-z0-9][A-Za-z0-9_-]*`; normalization is visible,
  deterministic, lowercase, and collision-failing.
- Title: trimmed, one line, 1–500 characters.
- Body: at most 256 KiB as UTF-8.
- Source ID and URL: at most 2,048 characters; URLs are HTTPS and contain no
  embedded credentials.
- Dependencies: unique valid IDs, no self-dependency.
- Acceptance criteria and labels: at most 100 unique, trimmed, single-line
  entries; each entry is at most 2,000 characters.
- Source state and updated timestamp are bounded observations, never workflow
  truth.

Output begins with `<!-- draindeck-intake:managed v1 -->`, uses LF, sorts by
canonical ID, and has exactly one trailing newline. Remote body lines that
could become `##` issue headings, `Depends-On:` records, or
`### Acceptance` sections are block-quoted. Only validated structured fields
can emit dependencies or acceptance criteria. Linear priority `1`–`4` becomes
the visible label `priority:<number>`; priority `0` emits no priority label.

An existing unmanaged file is refused unless `--force` is supplied. Symbolic
link destinations are refused. Publication acquires an adjacent exclusive
Intake lock, writes and fsyncs a temporary file in the destination directory,
revalidates the destination, then uses atomic replacement; byte-identical
managed content is not rewritten. The lock coordinates Intake processes and
the revalidation detects a changed destination before replacement; an
uncooperating external writer can still race the final OS replacement.

## Provider limits and trust boundary

- Collection rejects oversized pages, empty continuation pages, repeated or
  unchanged cursors, duplicate canonical IDs, and totals above `--max-issues`.
- The local adapter reads at most 10 MiB and requires UTF-8 plus the existing
  Draindeck parser contract.
- Remote transport allows only HTTPS and an exact adapter-supplied host,
  follows no redirects, caps request/response bytes, and accepts strict JSON
  only (including rejection of `NaN`/infinity). `--timeout-seconds` is the
  socket-operation timeout supplied by Python's standard HTTPS client, not a
  whole-sync deadline.
- GitHub is fixed to `api.github.com`, uses API version `2026-03-10`, requests
  open issues oldest-first, excludes objects containing `pull_request`, and
  consumes a bounded run of PR-only raw pages before deciding source exhaustion.
- Jira is restricted to an HTTPS `*.atlassian.net` root and uses enhanced JQL
  POST `/rest/api/3/search/jql` with a fixed field allowlist, consistent
  `isLast`/`nextPageToken` completion validation, and bounded ADF plain-text
  extraction.
- Linear is fixed to `https://api.linear.app/graphql`, filters by team key,
  uses Relay `first`/`after` for issues and labels (rejecting truncated label
  connections), and rejects any non-empty GraphQL `errors` array even on HTTP
  200.

These adapters intentionally fail closed on provider response drift. Their
committed tests use deterministic response fixtures; no live credentialed call
is part of the build evidence.

## Process contract

Success writes one stdout JSON object:

```json
{"contractVersion":1,"source":"github","issueCount":12,"outputPath":"C:\\target\\Issues.md","changed":true}
```

Failures write one stderr object with no stack trace or raw provider body:

```json
{"error":{"code":"source_error","message":"..."}}
```

Exit `0` means success, `2` means invalid command/configuration input, and `1`
means a source, transport, publication, or internal failure. Operators should
inspect the generated file and then invoke the existing runtime separately.

## Official provider references

- GitHub repository issues:
  <https://docs.github.com/en/rest/issues/issues#list-repository-issues>
- Jira Cloud enhanced JQL:
  <https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-post>
- Jira API-token Basic auth:
  <https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/>
- Jira REST v3 / ADF:
  <https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/>
- Linear GraphQL/auth/errors:
  <https://linear.app/developers/graphql>
- Linear pagination and filtering:
  <https://linear.app/developers/pagination>,
  <https://linear.app/developers/filtering>
