"""The context pack (doc 02 §5) — what a fresh ``claude -p`` session receives.

Pure function of the replayed projection + config. Three tiers (doc 02 §5): the
per-issue text, accumulated structured feedback from prior executions
(feedback-over-conversation, ADR-10), and a constraints block. Deliberately
UNDER-stuffs: no file contents, no repo map — the engine's own search tools pull
what it needs. The target repo's own CLAUDE.md is read by the engine naturally
because its cwd is the workspace.

Determinism matters: ``prompt_hash`` is recorded in ExecutionSpawned (intent),
and the same pack is rebuilt at spawn time, so this must be a pure function of
projection state — no timestamps, no environment reads.
"""
from __future__ import annotations

import hashlib

from ..events.projections import StateProjection


def build_prompt(proj: StateProjection, issue_id: str, validation_commands: list[str]) -> str:
    meta = proj.issue_meta.get(issue_id, {})
    lines: list[str] = []
    lines.append(f"# Issue {issue_id}: {meta.get('title', '').strip()}".rstrip())
    lines.append("")
    body = (meta.get("body") or "").strip()
    if body:
        lines.append(body)
        lines.append("")
    ac = meta.get("acceptance_criteria") or []
    if ac:
        lines.append("## Acceptance criteria")
        lines.extend(f"- {c}" for c in ac)
        lines.append("")

    feedback_block = _accumulated_feedback(proj, issue_id)
    if feedback_block:
        lines.append("## Feedback from previous attempts")
        lines.append(
            "Prior executions on this issue were rejected. Address every point "
            "below — repeating a mistake will escalate the issue out of the loop."
        )
        lines.extend(feedback_block)
        lines.append("")

    if validation_commands:
        lines.append("## Verify your work")
        lines.append("Your change must make these commands pass:")
        lines.extend(f"- `{c}`" for c in validation_commands)
        lines.append("")

    lines.append("## Constraints")
    lines.extend([
        "- Work ONLY inside this workspace directory.",
        "- Do NOT run git, commit, branch, push, or touch version control — the "
        "runtime owns all git operations and git tools are disabled for you.",
        "- Do NOT access the network or read credentials.",
        "- Implement the change directly by editing files; keep the diff minimal "
        "and focused on the issue.",
    ])
    return "\n".join(lines) + "\n"


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _accumulated_feedback(proj: StateProjection, issue_id: str) -> list[str]:
    """One bullet group per prior rejected execution: its taxonomy plus any
    reviewer feedback messages. Validation failures contribute their taxonomy
    (the detailed logs live under the artifacts dir, not the prompt)."""
    out: list[str] = []
    for xid in proj.issue_executions.get(issue_id, []):
        view = proj.executions[xid]
        if not view.taxonomy_category and not view.feedback:
            continue
        header = f"- Attempt {xid}"
        if view.taxonomy_category:
            header += f" ({view.taxonomy_category})"
        header += ":"
        out.append(header)
        for fb in view.feedback:
            cat = fb.get("category") if isinstance(fb, dict) else None
            msg = fb.get("message") if isinstance(fb, dict) else None
            if msg:
                out.append(f"  - [{cat}] {msg}" if cat else f"  - {msg}")
    return out
