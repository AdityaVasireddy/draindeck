"""Config generation for `draindeck init` (doc 16 §4 step 6). Renders
`config.local.yaml` as hand-written text — so per-line `# TODO:` comments
can sit next to the exact value they qualify, matching the existing
`config.local.yaml`/`config.example.yaml` style — while delegating every
interpolated scalar's YAML quoting/escaping to PyYAML rather than
hand-rolling it. No new schema keys are introduced anywhere; comments are
inert to `yaml.safe_load`/`load_config()` by construction.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import yaml

from .detect import CommandProposal, DetectionRow

# Verified against the actually-configured reviewer endpoint
# (http://localhost:11434/api/tags), not guessed: the bare `qwen2.5-coder`
# tag does not exist there, only `qwen2.5-coder:14b` does (14.8B, Q4_K_M —
# see docs/12-session4-engine-wrapper.md's Session-13 correction and
# config.local.yaml's own `reviewer.qwen.model` comment). `init` generates
# this exact tag rather than the bare, unresolvable one `config.example.yaml`
# still shows as a generic portable placeholder. This is a fixed default,
# not a live probe — see `render_config`'s docstring for why `init`/
# `check-config` do not query the reviewer endpoint at generation time.
_REVIEWER_MODEL = "qwen2.5-coder:14b"


def _scalar(value: str) -> str:
    """A single YAML scalar, correctly quoted/escaped for embedding in a
    hand-written template line. Never hand-roll YAML quoting rules —
    always delegate to PyYAML. Dumping the bare value directly
    (``yaml.safe_dump(value, ...)``) is unsafe: PyYAML appends an
    explicit ``...`` document-end marker after a PLAIN top-level scalar
    (verified empirically this session — e.g. ``yaml.safe_dump("my
    file.js", default_flow_style=True)`` returns ``"my file.js\\n...\\n"``),
    which ``.strip()`` does NOT remove (``...`` is not whitespace) and
    which would corrupt the surrounding structure when spliced inline.
    Wrapping the value in a one-key mapping sidesteps this entirely —
    mappings never get the document-end marker — then the ``key: ``
    prefix is stripped back off. Verified to round-trip through
    ``yaml.safe_load`` for plain, space-containing, backslash-containing,
    and colon-containing values alike.

    ``width=float("inf")`` is required: PyYAML's default 80-column width
    line-folds a long plain scalar across multiple lines (verified
    empirically this session — a long Windows path was split mid-string
    with a continuation line indented relative to the wrapping mapping,
    not to the caller's own template indentation, corrupting the
    surrounding structure). Disabling folding keeps every value on the
    single line the template expects.
    """
    dumped = yaml.safe_dump(
        {"x": value}, default_flow_style=False, width=float("inf")
    )
    return dumped[len("x: "):].rstrip("\n")


_RULE2_COMMENT = (
    "    # TODO: confirm — ADR-23 rule 2 (doc 08 §5d): this is bare\n"
    "    # pytest discovery, not explicit file targets. Narrow it to\n"
    "    # the exact test file(s) before relying on it unattended.\n"
)


def render_config(
    *,
    repo_path: Path,
    branch: str,
    branch_tip: str,
    all_matches: list[DetectionRow],
    chosen_stack: str,
    chosen: CommandProposal,
    today: Optional[Callable[[], date]] = None,
) -> str:
    """Full `config.local.yaml` text (no disk I/O — see `write_config`).
    Schema-identical to what `load_config` already parses: every key
    below exists in `Config`/`ProjectCfg`/`ValidationCfg`/etc. today, none
    are new (doc 16 §2 — Issue A never touches the schema). `engine`/
    `budget`/`experiment` are generic defaults mirroring
    `config.example.yaml` verbatim (not stack-detected — there is nothing
    in the repo to detect them from), flagged for review. `reviewer.qwen.
    model` deliberately does NOT mirror `config.example.yaml` verbatim —
    see `_REVIEWER_MODEL`'s comment; the example file's bare tag is a
    portable placeholder, not a value ever verified against a live
    endpoint. `billing.verified_on` is not a static default either: it is
    `today()`'s calendar date (`date.today()` unless a caller injects
    `today`, e.g. a test), matching the `YYYY-MM-DD` convention already
    used by `config.example.yaml`/`config.local.yaml`'s own
    `verified_on` values, in place of a `TODO: confirm` placeholder that
    isn't real verification evidence.

    Neither of these two fixes adds a live reviewer-endpoint probe: doing
    so would require `init`/`check-config` to grow network-coupled,
    reviewer-specific behavior neither has today (`check_config`/
    `validate_environment` in `config.py` only ever check repo/branch/env-
    var shape, never make a network call), which is out of scope here.
    `_REVIEWER_MODEL` is a fixed, repository-verified string; if the
    endpoint's available tags ever drift, that is caught the same way it
    always has been -- at reviewer-call time, not at generation time.
    """
    verified_on = (today or date.today)().isoformat()
    other = [row.stack for row in all_matches if row.stack != chosen_stack]
    other_comment = (
        f"# Also detected: {', '.join(other)} — see the priority table in\n"
        f"# docs/16-draindeck-init-spec.md §5 to switch."
        if other else "# No other stack markers detected."
    )

    if chosen.commands:
        rule2_comment = _RULE2_COMMENT if chosen.needs_rule2_confirm else ""
        commands_yaml = "\n".join(f"      - {_scalar(c)}" for c in chosen.commands)
        validation_block = f"""\
  validation:
    # TODO: confirm — this command was proposed by stack detection, not
    # verified against your test suite. Edit before a real run if needed.
    commands:
{commands_yaml}
{rule2_comment}    timeout_seconds: 600
"""
    else:
        # ADR-24 (doc 08 §5f): --no-validation was acknowledged. commands
        # is empty ONLY together with acknowledged_no_gate: true --
        # load_config refuses any other empty-commands config.
        validation_block = """\
  validation:
    # --no-validation was passed to `draindeck init`; no automated gate
    # will run for this drain. Remove `acknowledged_no_gate` and add real
    # commands to turn validation back on.
    commands: []
    acknowledged_no_gate: true
    timeout_seconds: 600
"""

    return f"""\
# Generated by `draindeck init` (docs/16-draindeck-init-spec.md).
# Detected stack: {chosen_stack} — review every # TODO before a real run.
{other_comment}
project:
  name: {_scalar(repo_path.name)}
  repository: {_scalar(str(repo_path))}
  branch: {_scalar(branch)}
  issues_file: Issues.md
{validation_block}# The sections below are generic defaults, not detected from this
# repository — review before a real run. Most match config.example.yaml
# verbatim; reviewer.qwen.model and billing.verified_on do not (see
# comments below) since a verbatim copy would be wrong here.
engine:
  provider: claude-headless
  auth_mode: subscription
  model: default
reviewer:
  provider: qwen
  qwen:
    endpoint: 'http://localhost:11434'
    model: {_scalar(_REVIEWER_MODEL)}  # repo-verified tag, not a placeholder
budget:
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  hard_stop_proxy_cost_per_run_usd: 15.0
experiment:
  sample_size: 20
  attempt1_success_min: 0.30
  cost_per_shipped_issue_max_usd: 3.0
billing:
  posture: pro_subscription_headless
  headless_split_status: paused
  verified_on: {_scalar(verified_on)}  # init-run date, not a TODO placeholder
  reverify_at: phase-2-gate
event_log:
  # Written explicitly (not left to Config's default) so it's visible here:
  # this path resolves against `project.repository` above, never the CWD
  # `draindeck run`/`recover` happens to be invoked from -- this repo's own
  # event log, isolated from every other target repo's.
  path: .draindeck/state/events.jsonl
"""


def write_config(path: Path, text: str) -> None:
    """The only disk-write entry point in this feature (doc 16 §4 step
    6). Callers decide *whether* to call this (preflight/confirm already
    passed); this function never decides on its own. Default destination
    is now `<repo>/.draindeck/config.local.yaml` (doc 16 §0b item 6,
    corrected) — the parent directory rarely pre-exists, so it's created
    here, at the point of the actual write, not earlier during preflight."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        fd, raw_temp_path = tempfile.mkstemp(prefix=".config.local.", suffix=".tmp", dir=path.parent)
        temp_path = Path(raw_temp_path)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        temp_path = None
        # Re-open the published name: a successful replace alone does not
        # prove that the final file's data reached stable storage.
        with path.open("r+b") as fh:
            os.fsync(fh.fileno())
        # Windows cannot open a directory this way.  On platforms that do
        # support it this persists the name replacement as well.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
