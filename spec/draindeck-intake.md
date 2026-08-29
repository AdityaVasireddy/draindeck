# Spec: Draindeck Intake v1

**Status:** ACCEPTED 2026-08-29 — explicit user approval of this specification,
ADR-28, the build-auto plan, and nine bounded local checkpoint commits. Push,
merge, live credentialed calls, dependency installation, and core runtime/event
changes remain unauthorized.

## Objective

Build an optional `draindeck_intake` package that imports issues from a local
`Issues.md`, GitHub, Jira Cloud, or Linear into one canonical, validated model
and compiles that model into the exact `Issues.md` format already consumed by
Draindeck. Intake is a one-way preflight tool, not workflow state: it never
opens or writes a Draindeck event log, imports `runtime.events`, invokes Git,
starts an engine, or edits `src/runtime`.

The operator can run one explicit command, inspect a machine-readable result,
and then start the existing runtime separately. Existing IDs already present in
a runtime event log remain immutable under the frozen Doc 03 contract; Intake
does not claim to update them.

## Scope

### Included

- `CanonicalIssueV1`, `IssuePage`, and `IssueSource` contracts.
- Bounded collection with cursor-cycle, duplicate-ID, and maximum-issue guards.
- Deterministic `Issues.md` compilation compatible with
  `runtime.queue.issues_md.parse`.
- Reserved-line quoting so untrusted remote body text cannot create headings,
  dependencies, or acceptance criteria in the generated queue.
- A local `Issues.md` source adapter.
- Read-only live adapters for:
  - GitHub repository issues (`GET /repos/{owner}/{repo}/issues`), excluding
    pull requests returned by the shared Issues endpoint.
  - Jira Cloud enhanced JQL search (`POST /rest/api/3/search/jql`) with
    `nextPageToken` and deterministic Atlassian Document Format text extraction.
  - Linear GraphQL issues with Relay `first`/`after` pagination.
- A standard-library HTTPS client with bounded response bodies, per-operation
  socket timeouts,
  redirect refusal, validated response JSON, and safe error mapping.
- Credentials loaded only from named environment variables.
- Coordinated managed-file writes: refuse to replace an unmanaged existing
  file unless `--force`; use an adjacent exclusive Intake lock and destination
  revalidation before atomic replacement; avoid rewriting identical bytes.
- `draindeck-intake sync {issues-md,github,jira,linear}` CLI with JSON success
  and error envelopes.

### Excluded

- Runtime source, event schema, state machine, queue projection, or observer
  changes.
- Bidirectional status synchronization or edits to GitHub/Jira/Linear.
- Updating an already-ingested issue in the event log.
- Complexity/risk classification and provider routing.
- GitHub Enterprise, Jira Data Center, OAuth browser flows, webhooks, polling
  daemons, SQLite state, Dashboard integration, and secret storage.
- Live credentialed API tests in the committed test suite.

## Public contracts

### Canonical issue

`CanonicalIssueV1` is immutable and validates at construction:

- `schema_version`: exactly `1`.
- `issue_id`: matches Draindeck's stable ID grammar
  `[A-Za-z0-9][A-Za-z0-9_-]*`.
- `source_kind`: one of `issues-md`, `github`, `jira`, `linear`.
- `source_id`: non-empty provider-native stable identifier, at most 2,048
  characters.
- `title`: one non-empty line, at most 500 Unicode code points.
- `body`: at most 256 KiB encoded as UTF-8.
- `depends_on`: unique valid Draindeck IDs, excluding `issue_id`.
- `acceptance_criteria`: at most 100 unique non-empty single-line entries, each
  at most 2,000 characters.
- `labels`: at most 100 unique non-empty single-line labels, each at most 2,000
  characters.
- `source_url`: optional HTTPS URL of at most 2,048 characters without embedded
  credentials.
- `source_state`: optional single-line source observation of at most 256
  characters; `updated_at`: optional single-line source observation of at most
  128 characters. Neither is workflow truth.

Adapters generate globally collision-resistant Draindeck IDs within their
configured source scope using a caller-visible prefix:

- GitHub: `<prefix>-<owner>-<repo>-<number>`.
- Jira: `<prefix>-<issue-key>`.
- Linear: `<prefix>-<identifier>`.
- Issues.md: the existing issue ID unchanged unless a prefix is explicitly
  supplied.

All segments are normalized to Draindeck's ID grammar. Normalization collisions
are rejected; they are never silently suffixed.

### Source protocol

```python
class IssueSource(Protocol):
    name: str

    def fetch_page(
        self, *, cursor: str | None, limit: int,
    ) -> IssuePage: ...
```

`IssuePage.issues` is immutable and `next_cursor` is opaque. Collection rejects
an unchanged/repeated cursor, an empty page with a continuation cursor, a page
larger than requested, duplicate canonical IDs, and totals beyond
`max_issues`.

### Generated Issues.md

Output is UTF-8 with LF newlines, a managed-file marker, stable lexicographic
ordering by `issue_id`, and exactly one trailing newline. Each issue uses the
existing syntax:

```markdown
## <id>: <title>

<quoted body>

Source: <source-kind>:<source-id>
Source-URL: <https-url>             # when present
Labels: <sorted comma list>         # when present
Depends-On: <ids>                   # when present
### Acceptance                     # when present
- <criterion>
```

Body lines from any source that would match `## ...`, `Depends-On: ...`, or
`### Acceptance` are block-quoted before rendering. Canonical dependencies and
acceptance criteria are emitted only from validated structured fields.

### CLI

```powershell
draindeck-intake sync issues-md --input C:\repo\Issues.md --output C:\managed\Issues.md
draindeck-intake sync github --owner OWNER --repo REPO --output C:\managed\Issues.md
draindeck-intake sync jira --base-url https://SITE.atlassian.net --jql "project = KEY" --output C:\managed\Issues.md
draindeck-intake sync linear --team-key ENG --output C:\managed\Issues.md
```

Common flags include `--id-prefix`, `--page-size`, `--max-issues`, `--force`,
and `--timeout-seconds`. Provider token arguments name environment variables;
secret values are never accepted as command-line arguments.

Success stdout is one JSON object containing `contractVersion`, `source`,
`issueCount`, `outputPath`, and `changed`. Errors go to stderr as
`{"error":{"code","message"}}` with no token, Authorization header, raw
response body, or stack trace. Exit codes: `0` success, `2` invalid input, `1`
source/transport/output failure.

## External API decisions

- GitHub uses `Accept: application/vnd.github+json`, API version `2026-03-10`,
  `state=open`, `sort=created`, `direction=asc`, and `per_page<=100`. A
  response object containing `pull_request` is excluded; bounded consecutive
  PR-only raw pages are consumed internally rather than treated as exhaustion.
- Jira Cloud permits only an HTTPS `*.atlassian.net` base URL in v1. It uses
  enhanced JQL POST with an explicit field allowlist, requires consistent
  `isLast`/`nextPageToken` completion signals, and uses Basic authorization
  from `<email>:<API token>` environment values. Password authentication is not
  supported.
- Linear uses only `https://api.linear.app/graphql`, personal API-key
  authorization from an environment variable, explicit `first`/`after`
  pagination for issues and labels, and rejects any non-empty GraphQL `errors`
  array even with HTTP 200.
- No adapter follows redirects while holding credentials. JSON requests and
  responses reject non-standard `NaN`/infinity constants.

Official references:

- GitHub repository issues:
  https://docs.github.com/en/rest/issues/issues#list-repository-issues
- Jira Cloud enhanced JQL search:
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-post
- Jira Cloud API-token basic authentication:
  https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
- Jira Cloud REST v3 and ADF fields:
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/
- Linear authentication and GraphQL errors:
  https://linear.app/developers/graphql
- Linear pagination:
  https://linear.app/developers/pagination
- Linear filtering:
  https://linear.app/developers/filtering

## Tech stack

- Python 3.12+
- Standard library HTTP/JSON/argparse/dataclasses/typing
- Existing project dependencies only (`pydantic` remains available but is not
  required for immutable domain objects)
- pytest using existing repository conventions

No dependency installation or lockfile change is authorized.

## Project structure

```text
src/draindeck_intake/
  __init__.py        public exports
  model.py           canonical contracts and validation
  compiler.py        deterministic Issues.md rendering
  sources.py         protocol, collection, shared source errors
  issues_md.py       local adapter
  http.py            bounded no-redirect JSON transport
  github.py          GitHub adapter
  jira.py            Jira adapter and ADF extraction
  linear.py          Linear adapter
  output.py          managed atomic file publication
  cli.py             command-line composition root
tests/intake/         focused unit/contract/CLI tests
docs/29-draindeck-intake.md
```

The package may import the existing pure `runtime.queue.issues_md.parse` only
inside the local adapter and compatibility tests. `src/runtime` never imports
Intake.

## Code style

Use frozen dataclasses, explicit typed errors, pure mapping functions, and
injected transports at external boundaries:

```python
@dataclass(frozen=True)
class IssuePage:
    issues: tuple[CanonicalIssueV1, ...]
    next_cursor: str | None = None


class GitHubSource:
    def __init__(self, transport: JsonTransport, *, owner: str, repo: str) -> None:
        self._transport = transport
        self._owner = owner
        self._repo = repo
```

## Testing strategy

- Every behavior is developed RED -> GREEN with focused pytest tests.
- Pure model/compiler tests cover limits, normalization, reserved-line quoting,
  stable output, duplicates, and parser compatibility.
- Collector tests cover pagination, cursor cycles, oversized pages, empty
  continuation pages, and maximum counts.
- HTTP tests use a local HTTP server or fake opener; no internet or credentials.
- Provider tests inject a fake transport and validate exact requests plus
  adversarial/malformed response shapes.
- CLI tests exercise local `Issues.md` end-to-end, managed overwrite rules,
  identical no-op writes, exit codes, and secret-free errors.
- Full verification runs `tests/unit`, `tests/intake`, `tests/dashboard`, both
  durability seeds, `compileall`, and `git diff --check`.

## Security and observability

Trust boundaries are CLI/config strings, local issue files, environment
credentials, HTTP status/headers, and provider JSON. Controls include strict
schema validation, size/count/time bounds, HTTPS and host allowlists, redirect
refusal, no credential CLI values, and allowlisted error details.

The CLI's JSON success/error envelope is the v1 operational signal. It answers:
which source ran, how many issues were accepted, whether output changed, and why
a run failed. V1 is an explicit foreground CLI, so metrics, tracing, alerts,
and a correlation store are out of scope.

## Boundaries

- Always: validate untrusted data at adapter boundaries; bound pages, totals,
  response bytes, strings, and per-operation network timeouts; run focused and
  regression tests before every local checkpoint commit; stage only owned files.
- Ask first: new dependencies, additional hosts, OAuth flows, persistence,
  runtime imports beyond the pure Issues.md parser, event/schema changes,
  Dashboard integration, or changes to an existing unmanaged output file
  without `--force`.
- Never: touch `src/runtime`; write/read event logs; invoke Git; mutate provider
  issues; accept secrets on argv; log tokens/headers/raw provider bodies; follow
  credentialed redirects; push or merge.
- Publication refuses symbolic-link destinations, serializes cooperating Intake
  processes with an adjacent exclusive lock, revalidates the destination before
  replacement, and fsyncs a same-directory temporary file before atomic
  replacement.

## Success criteria

1. All four source kinds map validated records into `CanonicalIssueV1`.
2. Generated bytes are deterministic and parse successfully with the current
   runtime parser without unintended synthetic issues/dependencies/acceptance.
3. Pagination and all external/local inputs are bounded and fail closed on
   malformed data.
4. Managed output publication refuses unmanaged overwrite by default,
   coordinates concurrent Intake publishers, revalidates before atomic
   replacement, and skips identical rewrites.
5. CLI success/errors follow the documented envelopes and never disclose
   credentials or raw provider payloads.
6. `src/runtime` and Doc 03 remain byte-unchanged; no new dependency is added.
7. Focused, combined, Dashboard, durability, compile, and diff checks pass.
8. Documentation includes commands, provider authentication, source limitations,
   and the immutable-after-ingestion warning.

## Open questions

None for v1. OAuth, enterprise hosts, bidirectional sync, classification, and
routing require separate specifications.
