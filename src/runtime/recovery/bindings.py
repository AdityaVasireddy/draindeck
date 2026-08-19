"""Reconciler seam bindings — compose a RepositoryAdapter with the
replayed projection to produce the events a crash prevented (docs/11 §2).

This is the only place that knows *both* git and the log: the adapter is
pure git mechanism, the reconciler is pure log mechanism, and
``bind_reconciler`` is the policy that joins them. The bindings never
mutate the log directly — they return event lists / residue refs that
``recover()`` appends through the one durable path.

Dependency direction (doc 09 §2): recovery → events, repo. Nothing here
is imported by the adapter or the log.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..events.projections import ExecutionView, StateProjection
from ..events.schema import Event, EventType
from ..state.model import ExecutionState, IssueState
from ..repo.adapter import RepositoryAdapter


def bind_reconciler(adapter: RepositoryAdapter, target_branch: str) -> dict:
    """Return the seam kwargs for ``recover()``: preserve_residue,
    recover_workspace, check_unwitnessed_commit, check_dirty_workspace."""

    def preserve_residue(view: ExecutionView) -> Optional[str]:
        """Check 1 (docs/11 §2.1). Re-entrant by construction: an existing
        ref short-circuits (window b6); a clean tree at a residue commit is
        captured via current_commit() (window b5); a clean tree still at the
        issue base means nothing happened (window b1).

        ``exclude_untracked=view.pre_execution_untracked`` (resolve-item,
        2026-08-18) keeps this execution's pre-spawn baseline (a target
        repo's own pre-existing untracked files, never Draindeck's) out of
        the residue commit — otherwise `git add -A` would sweep them in as
        tracked content, and check 3's later reset back to a commit that
        never had them would delete them as tracked removal, not preserve
        them (`preserve_untracked` on reset_hard only protects untracked
        paths from `clean -fd`, a different mechanism than this)."""
        ref = f"{_ns(adapter)}/{view.issue_id}/{view.execution_id}"
        if adapter.ref_target(ref) is not None:
            return ref                                  # b6: already preserved
        sha = adapter.snapshot_commit(
            f"crash residue {view.execution_id}",
            exclude_untracked=view.pre_execution_untracked,
        )
        residue = sha or adapter.current_commit()
        if sha is None and residue == view.base_commit:
            return None                                 # b1: nothing happened
        return adapter.set_attempt_ref(view.issue_id, view.execution_id, residue)

    def check_unwitnessed_commit(proj: StateProjection) -> list[Event]:
        """Check 2 (docs/11 §2.2). For each CommitIntent without its
        CommitCreated, ask git whether the merge happened (is_ancestor,
        doc 02 §4.2). Ancestor → backfill the fact; not → redo the merge
        (check-then-act) then record it."""
        out: list[Event] = []
        for view in proj.executions.values():
            if not (view.commit_intended and not view.commit_created):
                continue
            end = view.intent_end_commit
            target = view.intent_target_branch or target_branch
            if end is None:
                raise _tamper(f"CommitIntent for {view.execution_id} has no end_commit")
            if adapter.is_ancestor(end, target):
                mc = adapter.find_merge_commit(target, end)
                if mc is None:
                    # end is on target but no merge commit carries it as a
                    # second parent — the world was rewritten (squash/ff by a
                    # human). Forging the join key would corrupt everything
                    # downstream (ADR-11); surface it loudly instead.
                    raise _tamper(
                        f"{end[:12]} is on {target} but no merge commit "
                        f"witnesses it — refusing to forge merge_commit"
                    )
                backfilled = True
            else:
                mc = adapter.merge_to(target, end, f"merge {view.issue_id}")
                backfilled = False
            out.append(Event(
                type=EventType.COMMIT_CREATED,
                issue_id=view.issue_id,
                execution_id=view.execution_id,
                payload={"merge_commit": mc, "target_branch": target,
                         "backfilled": backfilled},
            ))
        return out

    def check_dirty_workspace(proj: StateProjection) -> list[Event]:
        """Check 3 (docs/11 §2.3). Restore the workspace to the commit the
        log's last pinned expectation implies, archiving any residue first.
        Emits no event (no such type in doc 03's frozen vocabulary); the
        ref + RecoveryReport.workspace_repairs are the evidence trail. The
        repair strings are threaded back via a side channel on the seam.

        Untracked-file provenance (resolve-item, 2026-08-18): a blanket
        ``is_dirty()`` cannot tell a target repo's own pre-existing
        untracked files (e.g. a real LUVZ smoke test's `Issues.md` and its
        backup) apart from genuine Draindeck crash residue — treating both
        as archivable/removable destroyed the former. The only untracked
        paths this check may treat as residue are ones NOT present in the
        relevant execution's `pre_execution_untracked` baseline (recorded
        at ExecutionSpawned, before the engine touched anything — see
        loop.py). With no active issue, or an active issue with no
        execution yet, there is no baseline to attribute any untracked
        path to, so untracked dirt is left alone entirely — only tracked/
        staged/conflicted dirt (`worktree_status().blocking`) or a genuine
        HEAD/expected-commit mismatch still triggers a reset, and even
        then every currently-untracked path is preserved through it."""
        expected = _expected_commit(proj, adapter, target_branch)
        if expected is None:
            return []  # nothing pinned yet (e.g. empty log) — nothing to do
        baseline = _untracked_ownership_baseline(proj)
        current_untracked = set(adapter.untracked_paths())
        blocking = adapter.worktree_status().blocking
        if baseline is None:
            owned_dirty = blocking
            preserve = current_untracked
        else:
            owned_dirty = blocking or bool(current_untracked - baseline)
            preserve = baseline & current_untracked
        head = adapter.current_commit()
        if owned_dirty or head != expected:
            # Archive residue unless check 1 already captured this exact
            # commit under an attempt ref (avoids double-archiving b7).
            already = head in set(adapter.list_attempt_refs().values())
            if owned_dirty or not already:
                # exclude_untracked=preserve: keep the same paths out of
                # this residue commit that reset_hard below will keep on
                # disk — otherwise add -A would sweep them in as tracked
                # content, and the reset would then delete them as tracked
                # removal (a different mechanism than clean -fd).
                sha = adapter.snapshot_commit("reconciler dirty-workspace",
                                              exclude_untracked=preserve)
                residue = sha or adapter.current_commit()
                if not (residue in set(adapter.list_attempt_refs().values())):
                    issue = _active_issue(proj) or "_recovery"
                    adapter.set_attempt_ref(
                        issue, f"reconciler-{proj.last_event_id}", residue)
                    check_dirty_workspace.repairs.append(
                        f"archived dirty workspace {residue[:12]} for {issue}")
            adapter.reset_hard(expected, preserve_untracked=preserve)
            check_dirty_workspace.repairs.append(f"reset workspace to {expected[:12]}")
        return []

    # side channel for check-3 repair strings (no event type for them)
    check_dirty_workspace.repairs = []  # type: ignore[attr-defined]

    return {
        "preserve_residue": preserve_residue,
        "recover_workspace": adapter.recover_workspace,
        "check_unwitnessed_commit": check_unwitnessed_commit,
        "check_dirty_workspace": check_dirty_workspace,
    }


# ── helpers ──────────────────────────────────────────────────────────
def _ns(adapter: RepositoryAdapter) -> str:
    # GitCliAdapter carries its namespace; fall back to the ADR-15 default.
    return getattr(adapter, "ns", "refs/attempts")


def _active_issue(proj: StateProjection) -> Optional[str]:
    for iid, st in proj.issues.items():
        if st is IssueState.ACTIVE:
            return iid
    return None


def _untracked_ownership_baseline(proj: StateProjection) -> Optional[set]:
    """Untracked paths that already existed before the currently-relevant
    execution's engine could have touched anything, or None if there is no
    execution to attribute any untracked path to (resolve-item, 2026-08-18).
    None is a stronger signal than an empty set: "no baseline" means check 3
    must not treat ANY untracked path as residue, where an empty set means
    the baseline is known and simply had nothing in it."""
    iid = _active_issue(proj)
    if iid is None:
        return None
    latest = proj.latest_execution(iid)
    if latest is None:
        return None
    return set(latest.pre_execution_untracked)


def _expected_commit(
    proj: StateProjection, adapter: RepositoryAdapter, target_branch: str
) -> Optional[str]:
    """The commit the workspace should sit at, from the log's last pinned
    expectation (docs/11 §2.3 table)."""
    iid = _active_issue(proj)
    if iid is not None:
        latest = proj.latest_execution(iid)
        if latest is not None:
            if latest.state in (ExecutionState.VALIDATING,
                                ExecutionState.REVIEWING,
                                ExecutionState.ACCEPTED):
                return latest.end_commit
            if latest.state in (ExecutionState.REJECTED, ExecutionState.CRASHED):
                return proj.issue_base_commit.get(iid)
        # active issue, no execution yet → sit at the issue base
        return proj.issue_base_commit.get(iid)
    return adapter.head_of(target_branch)


class ReconcilerTamperError(RuntimeError):
    """The world diverged from the log in a way recovery must not guess
    through (ADR-11 join-key integrity / honesty discipline)."""


def _tamper(msg: str) -> ReconcilerTamperError:
    return ReconcilerTamperError(msg)
