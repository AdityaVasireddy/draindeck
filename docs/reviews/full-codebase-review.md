# issue-runtime full codebase review

**Review type:** Read-only, full-codebase, evidence-graded. NO CODE CHANGES were made.
**Coverage:** PARTIAL, declared. See `coverage-ledger.md` for the exact fraction. The
entire tracked `src/` (27 files) and `tests/` (17 files) — 44/44 `.py` files, 100% —
plus all config files and a majority of design docs were read in full. A subset of the
36 historical `docs/handoffs/*.md` files, `docs/14` (1351 lines), `docs/handoffs/next-md-
archive-2026-07-26.md` (773 lines), and `docs/scratch/*.md` (993 lines) were **not** read
this pass — declared explicitly in the ledger, not silently narrowed. These are
low-blast-radius historical narrative docs per `CLAUDE.md`'s own effort-sizing rule, and
their material findings are largely re-surfaced via `NEXT.md`, doc 08, doc 12, and doc 15,
all of which **were** read in full.

---

## 0. State at review time

Raw output, Step 0:

```
$ git status --porcelain
(no output — clean)

$ git log --oneline -8
360e74b docs(handoff): session-34 close - Gap 4 shipped, issue-19 corrected, Gap 1 confirmed live on issue 26
8e92e87 feat(loop): persist num_turns on all ExecutionFinished events (Gap 4)
552f4b9 docs(next): correct issue-19 decomposition premise; log Gap 4 (num_turns not persisted)
a9b168a docs(handoff): session-33 close - 23/24 shipped, 25 hand-landed
f5e8d75 docs(next): session-33 gaps + issue-25 hand-land record
d4135bf docs(handoff): session-32 close - issue-19 decomposed (23/24/25), StockPhotoAgent tree cleaned
d6342bf docs(handoff): add session-27 gate-c/gate-d/SD handoff record
aedc659 chore: ignore scratch synth dirs; correct session-26 gate-(c) claim to UNWITNESSED

$ git rev-parse HEAD
360e74be8b8c28d99ef0d0014e0b4ffd9ed38895

$ git rev-parse --abbrev-ref HEAD
master

$ git log --oneline -1 7d2f4eb
7d2f4eb fix(engine): hold_pid gate on claude_headless spawn

$ git log --oneline -1 9c071ed
9c071ed fix(repo): scope attempt-ref GC to the completing execution (ADR-15 Amendment 1)

$ git log --oneline -1 5e63341
5e63341 fix(main): reorder recovery ahead of checkout_branch (ADR-20 Amendment 2)

$ git log --oneline -1 86e2476
86e2476 fix(main): restore project branch on all cmd_run exit paths

$ git log --oneline -1 3040c25
3040c25 docs(handoff): session-31 close — item-9 GAP-1 witnessed on scratch target, Layer-2 movement open

$ git log --oneline -1 f7573f8
f7573f8 docs(next): record item-9 GAP-1 witnessed on scratch (session 31)

$ git show --stat 3040c25
commit 3040c25f5932fbc07b719210b85fd7b0a27214c2
Author: Aditya User2 <vsaditya2020@gmail.com>
Date:   Mon Aug 3 17:25:36 2026 -0400

    docs(handoff): session-31 close — item-9 GAP-1 witnessed on scratch target, Layer-2 movement open
    [... 93 insertions, 1 new file: docs/handoffs/HANDOFF_2026-08-03_session31-item9-scratch-fault-injection.md]
```

**(a) Working tree clean?** YES — `git status --porcelain` returned no output.
**(b) HEAD on master, contains 7d2f4eb?** YES — HEAD is `360e74b` on `master`; `git log
--oneline -1 7d2f4eb` resolves cleanly (the commit is an ancestor of HEAD; `master`'s log
in part (a) of Step 0 does not directly list it but the direct lookup succeeds, confirming
it is reachable history — VERIFIED by the successful `git log -1 <sha>` resolution, not
by eyeballing the 8-line log).
**(c) docs/handoffs/ contains the session-31 handoff?** YES — `git show --stat 3040c25`
confirms the commit adds exactly
`docs/handoffs/HANDOFF_2026-08-03_session31-item9-scratch-fault-injection.md` (93 lines,
new file), and this file is present in the current tree (confirmed via `git ls-files`
in Step 1 and read directly in Pass 5).

Since (a) is YES, the review proceeded per the task spec.

---

## 1. Inventory

Raw counts, Step 1:

```
$ git ls-files | Measure-Object -Line
Lines Words Characters Property
----- ----- ---------- --------
  108
```

**Total tracked files: 108.**

**.py files: 44, combined 7,448 lines.** (Per-file table, `git ls-files "*.py" |
ForEach-Object {...} | Sort-Object File | Format-Table`, PowerShell `$_` mangled under the
Bash-tool's Git-Bash wrapper on first attempt — worked around by writing the command to a
`.ps1` script file and invoking `powershell -File`, per the task's own guidance.)

```
File                                    Lines
----                                    -----
src/runtime/__init__.py                     0
src/runtime/budget/__init__.py              7
src/runtime/budget/manager.py              71
src/runtime/config.py                     180
src/runtime/context/__init__.py             7
src/runtime/context/pack.py                87
src/runtime/engine/__init__.py             19
src/runtime/engine/claude_headless.py     767
src/runtime/events/__init__.py              0
src/runtime/events/log.py                 150
src/runtime/events/projections.py         268
src/runtime/events/schema.py              130
src/runtime/loop.py                       357
src/runtime/main.py                       311
src/runtime/queue/__init__.py               6
src/runtime/queue/issues_md.py             98
src/runtime/recovery/__init__.py            0
src/runtime/recovery/bindings.py          156
src/runtime/recovery/reconciler.py        130
src/runtime/repo/__init__.py               18
src/runtime/repo/adapter.py               159
src/runtime/repo/git_adapter.py           262
src/runtime/reviewer/__init__.py           21
src/runtime/reviewer/base.py               88
src/runtime/reviewer/qwen_ollama.py       170
src/runtime/validation/__init__.py          6
src/runtime/validation/runner.py          138
tests/__init__.py                           0
tests/crash/__init__.py                     0
tests/crash/harness.py                    620
tests/crash/item9_orphan_harness.py       834
tests/crash/worker.py                     278
tests/unit/__init__.py                      0
tests/unit/test_bindings.py               246
tests/unit/test_engine.py                 342
tests/unit/test_engine_adr22.py            84
tests/unit/test_foundation.py             312
tests/unit/test_git_adapter.py            261
tests/unit/test_loop.py                   309
tests/unit/test_loop_real_git.py          130
tests/unit/test_main.py                    63
tests/unit/test_main_exit_paths.py        117
tests/unit/test_seams.py                  150
tests/unit/test_validation_env_adr23.py    96
```
Sum verified via `wc -l` cross-check = 7,448. File count verified via `git ls-files "*.py"
| wc -l` = 44.

**yaml/yml/toml/cfg/ini/json bucket: 3 files.**
```
config.example.yaml
config.yaml
pyproject.toml
```

**.md files: 59.** (Full list read in Pass 4/5; enumerated in the coverage ledger.)

**Everything else (not py/yaml/yml/toml/cfg/ini/json/md): 2 files.**
```
.gitattributes
.gitignore
```

**Three explicit numbers (Step 1 requirement):**
- Total tracked files: **108**
- Total `.py` files: **44**, combined **7,448** lines
- Other buckets: yaml/yml/toml/cfg/ini/json = **3**; `.md` = **59**; everything else = **2**

Sum check: 44 + 3 + 59 + 2 = 108. Matches `git ls-files | wc -l`.

**Untracked-but-load-bearing discovery (not in the Step-1 inventory, flagged separately):**
`src/runtime/state/` (containing `model.py`, `transitions.py`, `__init__.py` — the actual
frozen-contract state machine, doc 03 §§1–2) is **not tracked by git at all**. `git
ls-files src/runtime/state/` returns nothing; `git status --porcelain --ignored=matching
-- src/runtime/state/` shows `!! src/runtime/state/`; `git check-ignore -v` on all three
files resolves to `.gitignore:1:state/`. This is Tier A finding **A-CRIT-1** below. Because
Step 1's inventory is built from `git ls-files` per the task's own instruction, these three
files do **not** appear in the coverage-ledger's denominator — but they were read in full
this session (quoted in full below) because they are load-bearing production code.

---

## 2. Tier A findings — durability & recovery contract

### A-CRIT-1 | VERIFIED | `.gitignore:1`, `src/runtime/state/{model.py,transitions.py,__init__.py}`

```
.gitignore:1:  state/
```
```
$ git check-ignore -v src/runtime/state/model.py src/runtime/state/transitions.py src/runtime/state/__init__.py
.gitignore:1:state/	src/runtime/state/model.py
.gitignore:1:state/	src/runtime/state/transitions.py
.gitignore:1:state/	src/runtime/state/__init__.py
```

**What is wrong.** `.gitignore` line 1 is the bare, unanchored pattern `state/`. Git
gitignore syntax matches an unanchored directory pattern at **any depth**, not just the
repo root — so this line silently ignores `src/runtime/state/` (the actual state-machine
implementation: `IssueState`/`ExecutionState` enums and the exhaustive legal-transition
tables doc 03 declares FROZEN) in addition to whatever top-level `state/` runtime-data
directory (`state/events.jsonl`, `state/artifacts/`) the pattern was clearly written for
(see doc 09 §1's folder layout, which places the runtime's *data* directory at repo-root
`state/`). The result: `src/runtime/state/model.py` and `src/runtime/state/transitions.py`
— imported by `loop.py:37`, `events/projections.py:13-19`, `recovery/bindings.py:19`, and
seven test files (`test_bindings.py`, `harness.py`, `worker.py`, `test_foundation.py`
(twice), `test_loop.py`, `test_loop_real_git.py`) — have **zero git history**. They exist
only as working-tree files. A fresh `git clone` of this repository would be missing files
its own `main.py`/`loop.py` cannot import without, i.e. the checked-out repository would
not run. Any `git clean -fdx`, `git stash -u` mishap, disk loss, or machine migration that
relies on git as the durability backstop would silently destroy the frozen state machine
with no recovery path — the single most severe kind of gap a durability-focused project
can have, and it sits in the project's own source control hygiene rather than in the
runtime it builds.

**Proposed fix (NOT applied):**
```diff
--- a/.gitignore
+++ b/.gitignore
@@ -1,4 +1,4 @@
-state/
+/state/
 __pycache__/
 *.torn.*
 
```
(Anchoring the pattern to the repo root with a leading `/` scopes it to the intended
runtime-data directory only; `src/runtime/state/` would then need `git add -f
src/runtime/state/` once to bring it under version control — a repository-mutation action
requiring Adi's explicit authorization, not performed this session.)

---

### A1 — event log fsync-before-state-advance

**VERIFIED**, `src/runtime/events/log.py:46-62`:
```python
def append(self, event: Event) -> int:
    """Assign the next event_id, persist durably, return it."""
    eid = self._last_event_id + 1
    persisted = Event(...)
    self._fh.write(persisted.to_line())
    self._fh.flush()
    os.fsync(self._fh.fileno())
    self._last_event_id = eid
    return eid
```
Write → flush → `os.fsync` happen strictly before `self._last_event_id` (the log's own
in-memory cursor) is advanced and before `append()` returns an `event_id` to any caller.

Every caller found in `src/` follows the same append-then-apply order:
- `src/runtime/loop.py:85-90` (`Orchestrator._emit`): `eid = self.log.append(ev)` on the
  line before `self.proj.apply(...)` — projection state advances strictly after the
  durable append.
- `src/runtime/recovery/reconciler.py:122-130` (`_emit`): identical shape, `log.append(ev)`
  then `proj.apply(persisted)`.
- `src/runtime/main.py:144-146` (`_ingest_issues`): `eid = log.append(ev)` then
  `proj.apply(Event(...))`.

No path was found in `src/` where in-memory/projection state advances before
`EventLog.append()` returns. **Tier A1: VERIFIED.**

---

### A2 — event type → append site(s) → replay handler

All 15 `EventType` values (`events/schema.py:32-46`), traced against every append call
site found in `src/` and the handler dispatch table in `events/projections.py:252-268`
(`_HANDLERS`):

| # | Event type | Append site(s) | Replay handler |
|---|---|---|---|
| 1 | `IssueCreated` | `main.py:144` (`_ingest_issues`) | `_issue_created` |
| 2 | `IssueActivated` | `loop.py:155-156` (`_activate`) | `_issue_transition` |
| 3 | `ExecutionSpawned` | `loop.py:186-187` (`_spawn_or_escalate`) | `_execution_spawned` |
| 4 | `ExecutionFinished` | `loop.py:235-238`, `loop.py:249-250`, `loop.py:254-257` (`_execute`/`_finish_rejected`) | `_execution_transition` |
| 5 | `ExecutionCrashed` | `reconciler.py:89-96` (`recover()` check 1) | `_execution_transition` |
| 6 | `ValidationPassed` | `loop.py:264-268` (`_validate`) | `_execution_transition` |
| 7 | `ValidationFailed` | `loop.py:270-275` (`_validate`) | `_execution_transition` |
| 8 | `ReviewApproved` | `loop.py:289-293` (`_review`) | `_execution_transition` |
| 9 | `ReviewRejected` | `loop.py:295-301` (`_review`) | `_execution_transition` |
| 10 | `CommitIntent` | `loop.py:314-317` (`_commit_sequence`) | `_commit_intent` |
| 11 | `CommitCreated` | `loop.py:331-334` (`_commit_sequence`); `recovery/bindings.py:69-75` (`check_unwitnessed_commit`) | `_commit_created` |
| 12 | `IssueCompleted` | `loop.py:340-342` (`_commit_sequence`) | `_issue_transition` |
| 13 | `IssueEscalated` | `loop.py:194` (`_escalate`); `loop.py:239-243` (turn-budget branch) | `_issue_transition` |
| 14 | `HumanIntervention` | **none found in `src/`** | **no entry in `_HANDLERS`** |
| 15 | `GuidelinePromoted` | **none found in `src/`** | **no entry in `_HANDLERS`** |

**Two types with neither an append site nor a handler: `HumanIntervention`,
`GuidelinePromoted`.** This matches `events/projections.py:266-268`'s own comment ("counted;
no state machine in the foundation — escalation handling arrives with the orchestrator")
and is not itself a defect — declared, not silently dropped — but it means both types are
currently **inert**: nothing in `src/` can ever emit them, so `StateProjection.apply()`'s
generic `self.counts[ev.type.value] += 1` (projections.py:60) would count them if they ever
appeared (e.g. injected by a future human-intervention CLI), but no code path exists to
create that event today. **Tier A2: VERIFIED** — table complete, no silent app-without-
handler or handler-without-app pairs among the 13 active types; the 2 inert types are named
explicitly rather than glossed over.

---

### A3 — reconciler three-check firing order

**VERIFIED**, `src/runtime/recovery/reconciler.py:57-119` (`recover()`):
```
79   if recover_workspace is not None:
80-81   report.workspace_repairs.extend(recover_workspace())
83   report.checks_run.append("orphaned_execution")
84-98  for view in proj.open_executions(): ...   # CHECK 1
100  for name, fn in (
101      ("unwitnessed_commit", check_unwitnessed_commit),   # CHECK 2
104      ("dirty_workspace", check_dirty_workspace),          # CHECK 3
105  ):
106-117  ... (checks_run.append(name); fn(proj); harvest .repairs)
```

**Exact order: `recover_workspace()` (stale-lock clear) → Check 1 (orphaned execution) →
Check 2 (unwitnessed commit) → Check 3 (dirty workspace).**

This **corrects** a premise in the task's own A3 prompt. The task asked to "Confirm the
dirty-workspace check still fires unconditionally BEFORE checkout and ingest... **before
any orphan recovery**." Two separate claims are bundled there:
1. *"Fires before checkout and ingest"* — **TRUE**. `recover()` as a whole (all three
   checks) runs at `main.py` step 7, entirely before `checkout_branch` (step 7b) and
   `_ingest_issues` (step 9) — confirmed by reading `main.py:181-248` directly.
2. *"Before any orphan recovery"* — **FALSE**. Check 3 (dirty workspace) is the **last** of
   the three checks in `recover()`'s own source, running strictly **after** Check 1
   (orphaned execution). This is deliberate and documented — `reconciler.py:1-17`'s module
   docstring states "Check 1 (log-complete here)... Checks 2 and 3... need the
   RepositoryAdapter" — Check 1 has no repo dependency and is coded first; Checks 2/3 are
   iterated together afterward. `docs/15-item9-outcome-matrix.md` line 11 independently
   confirms this same order was traced and relied upon in the project's own design-gate
   analysis: "check 1... unconditionally precedes check 3... check 3's `already` guard...
   makes its own archival step a no-op once check 1 has already recorded the residue ref."

Confirmed the second half of A3's mechanism claim: `check_dirty_workspace`
(`recovery/bindings.py:78-104`) does perform `git add -A` + `git commit --no-verify` +
`reset_hard`, but **conditionally**, not unconditionally — it calls
`adapter.snapshot_commit(...)` (which internally is `git_adapter.py:176-184`: `self._git("add",
"-A")` then `self._git("commit", "--no-verify", ...)`) only `if dirty or not already` (line
93), and `adapter.reset_hard(expected)` (`git_adapter.py:203-205`: `git reset --hard` +
`git clean -fd`) only `if dirty or head != expected` (line 89). The check itself is always
*invoked* (appears in `report.checks_run` whenever the binding is supplied), but its
mutating side effects fire only when the tree is actually dirty or mispositioned — and by
construction it runs last among the three, not first.

**Proposed fix:** none — this is a "confirm/correct" finding, not a code defect. The actual
ordering (Check 1 before Check 3) is intentional and internally consistent with doc 03's
"residue is preserved to an attempt ref, then `ExecutionCrashed` is emitted, then the
workspace is reset" ordering law, quoted verbatim in the reconciler's own docstring and in
`docs/08` ADR-20 Amendment 2. Recorded here as a correction to the task's stated premise,
not as a bug to fix.

---

### A4 — no-double-commit: every merge-commit-creating path

**VERIFIED.** `RepositoryAdapter.merge_to` (`repo/git_adapter.py:207-238`) is the **only**
method in the codebase that creates a merge commit (`git commit-tree ... -p <target_head>
-p <commit>` then `git update-ref refs/heads/<target> <mc> <target_head>`, lines 232-236).
Two call sites exist in `src/`:

1. `loop.py:329` (`Orchestrator._commit_sequence`, normal completion path).
2. `recovery/bindings.py:67` (`check_unwitnessed_commit`, the reconciler's redo branch).

For **both**, the call is gated by a check-then-act `is_ancestor` test immediately before
it, and — critically — by `find_merge_commit` (a **content-based, second-parent** lookup,
`git_adapter.py:147-162`, one pass over `git rev-list --first-parent --merges --parents
<target>` matching `toks[2] == merged_full`) rather than event/ref cardinality alone:

- `loop.py:319-330`:
  ```python
  if self.adapter.is_ancestor(end, self.target):
      mc = self.adapter.find_merge_commit(self.target, end)
      if mc is None:
          raise OrchestratorHalt(...)   # refuses to forge the join key
      backfilled = True
  else:
      mc = self.adapter.merge_to(self.target, end, f"merge {issue}")
      backfilled = False
  ```
- `recovery/bindings.py:53-68` (`check_unwitnessed_commit`): the identical shape —
  `is_ancestor` → `find_merge_commit` → `_tamper()` if the ancestor exists but no merge
  commit witnesses it (raises `ReconcilerTamperError`, refusing to forge), else `merge_to`.

Both call sites therefore satisfy the task's stated load-bearing requirement directly: the
guard against a second merge of the same work is `find_merge_commit`'s content-addressed
second-parent scan, not merely "does a `CommitCreated` event already exist" (event
cardinality) or "does the attempt ref still exist" (ref cardinality) — either of which
could, in principle, be spoofed or stale. **No path relying on cardinality alone was
found; both merge-creating call sites use the content check.** `Orchestrator._commit_sequence`
additionally short-circuits before even reaching this logic via
`if not ex.commit_created:` (`loop.py:319`), itself driven by the projection's replay of
`CommitCreated`/`CommitIntent` state — but the code comment at `git_adapter.py:6-7` is
explicit that the object-DB merge's crash-safety rests on `is_ancestor`, "doc 02 §4.2's
witness," not on the log.

---

### A5 — `delete_attempt_ref` is execution-scoped (ADR-15 Amendment 1)

**VERIFIED**, exact lines:

`loop.py:336-343` (`_commit_sequence`, the sole production call site):
```python
        # both done → close the issue, then GC this execution's own attempt
        # ref (ADR-15 Amendment 1: scoped to the completing execution, not
        # the whole issue — its content is already reachable via the merge
        # above; a crashed sibling execution's residue ref must survive this GC)
        self._emit(self._event(EventType.ISSUE_COMPLETED, issue,
                               {"reason": "accepted",
                                "evidence_refs": [ex.end_commit]}))
        self.adapter.delete_attempt_ref(issue, ex.execution_id)  # idempotent
```

`repo/git_adapter.py:240-245` (implementation, single-ref-scoped, not the issue-wide glob):
```python
    def delete_attempt_ref(self, issue_id: str, execution_id: str) -> bool:
        ref = f"{self.ns}/{issue_id}/{execution_id}"
        if self.ref_target(ref) is None:
            return False
        self._git("update-ref", "-d", ref)
        return True
```

`repo/adapter.py:143-150` (interface contract, states the amendment's rationale directly in
the docstring): "ADR-15 Amendment 1: GC is scoped to the COMPLETING execution's own
now-redundant ref... never the whole issue, which would collaterally delete a crashed
sibling execution's only residue anchor."

The prior, issue-scoped `delete_attempt_refs(issue_id)` method (plural) — the one that
caused the documented item-14 evidence-loss defect (`docs/08` §5e) — no longer exists
anywhere in `src/`; confirmed both by direct reading of `repo/adapter.py` and
`repo/git_adapter.py` (no such method present) and by the unit test
`test_git_adapter.py:201-211` (`test_delete_attempt_ref_is_execution_scoped`) asserting a
sibling execution's ref survives.

---

## 3. Tier B findings — hold_pid / liveness

### B-CRIT-1 | VERIFIED | `src/runtime/engine/claude_headless.py:409-423`, `409-423` cross-referenced against `531-569`, `346-347`

**This is the single highest-severity finding of the review — see §7/Step 6(e).**

`ClaudeHeadlessEngine.is_execution_alive` — the method bound directly into
`recover()`'s `is_execution_alive` seam at `main.py:198` (`is_execution_alive=
engine.is_execution_alive`) and consulted by `reap_orphans()` (`claude_headless.py:398-406`)
— is:
```python
409  def is_execution_alive(self, execution_id: str) -> bool:
410      """Reconciler seam. True only if the pidfile exists, the pid is running,
411      AND its current image matches the image recorded at spawn (defeats PID
412      reuse without psutil). Any mismatch/missing → False, and the stale
413      pidfile is removed. No locks: doc 01 guarantees single-writer,
414      sequential execution, and recovery is startup-only, so there is no
415      concurrent access to guard."""
416      pidfile = self._pidfile(execution_id)
417      rec = _read_pidfile(pidfile)
418      if rec is None:
419          return False
420      if _alive_by_record(rec):
421          return True
422      pidfile.unlink(missing_ok=True)  # stale — clean up
423      return False
```
`rec["pid"]` is written by `_write_pidfile` at spawn time to `proc.pid`
(`run()`, line 303: `self._write_pidfile(pidfile, proc.pid)`) — i.e. the **direct child of
`subprocess.Popen(argv, ...)`**, which on Windows is the `claude.CMD` npm shim
(`cmd.exe`), per the module's own header comment (lines 30-33): "On Windows `claude` is an
npm `.CMD` shim: it MUST be resolved with `shutil.which`... and runs under cmd.exe, so the
real node/claude process and its tool subprocesses are DESCENDANTS of `proc.pid` — tree-kill
is required, not a single kill." `_alive_by_record` (lines 712-722) checks only whether
*that pid* — the shim — is currently running (plus an image-match to defeat pid reuse). It
never walks descendants.

The code that **does** correctly resolve past the shim to the real leaf worker —
`_resolve_leaf_worker` (lines 531-569), the "LAYER 1" mechanism landed in commit `7d2f4eb`
("hold_pid gate on claude_headless spawn") specifically because, per the module's own
comment at lines 450-457: *"Confirmed 3x live against real StockPhotoAgent runs: the
recorded child_pid (a claude.CMD shim -> cmd.exe) reliably exits shortly after handing off
to the real worker, while work visibly continues on disk — 'is child_pid alive' is
unfalsifiable as an orphan witness"* — is called from exactly **one** site,
`_sentinel_pause` (line 591), which is itself invoked from `run()` **only when**
`os.environ.get("ITEM9_SENTINEL") == "1"` (lines 346-347). `is_execution_alive` and
`reap_orphans` **never call `_resolve_leaf_worker` or `_sentinel_pause`** — confirmed by a
repository-wide grep for `_resolve_leaf_worker`/`is_execution_alive` (the only two call
sites for the former are line 591's assignment and its own definition; `is_execution_alive`
has no reference to leaf-resolution anywhere in its body).

**Consequence, in production (`ITEM9_SENTINEL` unset, the only mode any real
`cmd_run`/`python -m runtime.main run` invocation uses):** the very failure mode the
module's own comments name as "unfalsifiable" is exactly the liveness check
`reap_orphans()` and `recover()`'s check 1 actually run on every startup. If the
`claude.CMD` shim has exited (its own documented, common behavior — "reliably exits shortly
after handing off to the real worker") while a real descendant process is still mid-edit on
the target repository, `is_execution_alive` returns `False`: `reap_orphans` silently
unlinks the pidfile without entering its `if _alive_by_record(rec): _kill_tree(...)` branch
(no repair reported, no kill attempted — `claude_headless.py:400-406`), and
`recover()`'s check 1 treats the execution as already-dead, preserves whatever residue is
on disk *at that instant* (via `preserve_residue`/`snapshot_commit`), emits
`ExecutionCrashed`, and resets the workspace — while the real leaf process may continue
running and mutating files on disk **after** the reset, completely unsupervised and
untracked by any event. This is precisely the risk `NEXT.md` item 9's "Session 24
follow-up" already witnessed once in the wild (before the item-13 reorder fix): *"the
orphaned child ran to completion fully unsupervised and left a real edit on the target
repo's per-issue attempt branch... with ZERO event-log trace."* The Layer-1/hold_pid work
that followed (commit `7d2f4eb`) built the correct descendant-walking discriminator, but
never wired it into the actual `is_execution_alive`/`reap_orphans` decision path used by
real runs — only into a test/fault-injection observation harness gated behind an
environment variable that production code never sets.

**Proposed fix (NOT applied — this is `src/` behavior change, high-blast-radius, requires
an ADR and the 60/60-both-seeds durability gate per `CLAUDE.md`):**
```diff
--- a/src/runtime/engine/claude_headless.py
+++ b/src/runtime/engine/claude_headless.py
@@ -406,15 +406,17 @@ class ClaudeHeadlessEngine:
     def is_execution_alive(self, execution_id: str) -> bool:
-        """Reconciler seam. True only if the pidfile exists, the pid is running,
-        AND its current image matches the image recorded at spawn (defeats PID
-        reuse without psutil). Any mismatch/missing → False, and the stale
-        pidfile is removed. No locks: doc 01 guarantees single-writer,
-        sequential execution, and recovery is startup-only, so there is no
-        concurrent access to guard."""
+        """Reconciler seam. Walks descendants of the recorded (shim) pid via
+        _resolve_leaf_worker — the shim itself commonly exits before the real
+        worker does (see LAYER 1 comment above) — and returns True iff any
+        live descendant is found, not merely the shim pid. Any mismatch/
+        missing/no-descendants → False, and the stale pidfile is removed."""
         pidfile = self._pidfile(execution_id)
         rec = _read_pidfile(pidfile)
         if rec is None:
             return False
-        if _alive_by_record(rec):
+        if _alive_by_record(rec):
             return True
+        descendants, _ = _walk_descendants(rec["pid"])
+        if any(_pid_image(p) is not None for p in descendants):
+            return True
         pidfile.unlink(missing_ok=True)  # stale — clean up
         return False
```
(Sketch only — the real fix needs its own design pass: bounded polling akin to
`_resolve_leaf_worker`'s stability loop may be needed rather than a single unbounded
descendant walk, and `reap_orphans`'s kill target would need to become the whole descendant
set, not just `rec["pid"]`, since `_kill_tree`'s `taskkill /F /T` already walks the tree
*at kill time* from the given pid — but if that pid (the shim) is already gone, `/T` has
nothing to walk from. This is exactly the "known limitation" the module's own docstring
names at lines 42-49.)

---

### B1 — `_resolve_leaf_worker` bound and behavior at the cap

**VERIFIED**, `claude_headless.py:449-461`:
```python
_LEAF_MAX_POLLS = 20
_LEAF_MAX_SECONDS = 10.0
_LEAF_POLL_INTERVAL = 0.5
_LEAF_STABLE_COUNT = 3
```
Confirms the task's stated bound exactly: 20 polls, 10s wall-clock cap, 3-consecutive-
stable requirement.

**What happens when the bound is hit without a stable leaf** — `claude_headless.py:562-569`:
```python
        if i >= max_polls or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)
    reason = (
        f"leaf did not repeat for {stable_count} consecutive polls within "
        f"{len(poll_log)} poll(s) / {max_seconds}s cap"
    )
    return descendants, None, poll_log, reason
```
**Log, not raise, not silent.** The function returns `leaf_worker_pid=None` plus a
human-readable `reason` string — it never raises. The caller, `_sentinel_pause`
(lines 591-639), writes both into the `sentinel_ready` marker JSON (`"leaf_worker_pid":
leaf_worker_pid, "leaf_worker_reason": reason`, lines 632-633) and prints a `[sentinel]`
line to stdout naming `leaf_worker_pid=None` (line 638) — so the failure is recorded and
surfaced, not swallowed. However, execution *does* proceed regardless: `_sentinel_pause`
continues to write the marker and block on `sentinel_resume` even with no resolved leaf
(there is no early-return or halt on `reason is not None`). **Caveat that changes this
finding's practical weight:** this entire code path — `_resolve_leaf_worker`,
`_sentinel_pause`, and everything that calls them — executes only when
`ITEM9_SENTINEL=1` is set in the environment (`run()`, line 346), which no production
invocation of `cmd_run`/`main.py run` sets. In production this bound is never reached
because the code containing it never runs.

---

### B2 — hold_pid companion process reaping

**VERIFIED for the mechanism; NOT-OBSERVABLE for "the normal, non-crash exit path" as
literally framed, because no such path exists in production — the entire mechanism is
test-only (see B1's caveat).**

`_sentinel_pause` (`claude_headless.py:604-624`):
```python
    hold_script = (
        "import pathlib, time;"
        f"pathlib.Path(r'{hold_ready}').touch();"
        f"\nwhile not pathlib.Path(r'{resume}').exists():"
        "\n    time.sleep(0.2)"
    )
    hold_proc = subprocess.Popen([sys.executable, "-c", hold_script])
    ...
    while not hold_ready.exists():
        if time.monotonic() >= hold_deadline:
            raise RuntimeError(...)
        time.sleep(0.05)
```
`hold_proc` is a Python subprocess whose entire body is a polling loop on the existence of
a `sentinel_resume` file. **Nothing in `claude_headless.py` ever calls `hold_proc.wait()`
or `hold_proc.kill()` explicitly.** Its only exit path is self-termination: once an
external actor (a fault-injection harness, or a human, per the function's own docstring at
lines 582-585: "a fault-injection harness (or a human) does that from outside") creates the
`sentinel_resume` file, `hold_proc`'s own `while` loop condition becomes false and the
Python interpreter exits normally. The parent `run()` method itself never joins on
`hold_proc` — after `_sentinel_pause` returns, control proceeds to `proc.wait(timeout=...)`
on the **original** `proc` (the claude/dummy child), not on `hold_proc`. Every session
handoff describing a *miss* (a witness never landing) instead relies on an **external**
`taskkill /PID <pid> /T /F` against the whole tree to reap `hold_proc` alongside everything
else (`docs/handoffs/HANDOFF_2026-08-01_session26-group-s-holdpid-queue-block.md`:
"Miss-cleanup default corrected to `taskkill /PID <pid> /T /F`... on an S-A′ witness miss").
**Every exit path that leaves `hold_proc` running is therefore: any crash/kill of the
orchestrator process itself, without an external harness subsequently writing
`sentinel_resume` or tree-killing the whole process group** — at which point `hold_proc`
becomes an orphaned, indefinitely-polling child with no code-side backstop timeout of its
own (only the *caller's* 2-second wait for `hold_ready` is time-bounded; the loop on
`sentinel_resume` itself has no deadline). This is consistent with the design's own stated
intent (a human/harness resumes it deliberately) but the module has no self-timeout for
`hold_proc` if that external actor never shows up.

---

### B3 — `capture_work_liveness`: both layers captured, but the AND is procedural, not code-enforced

**VERIFIED that both mtime and sha256 are captured; VERIFIED (by absence) that no code
anywhere enforces the "both layers positive" AND as a gate — that requirement lives only in
design documentation (`docs/15-item9-outcome-matrix.md` §6) as a human-executed protocol.**

`claude_headless.py:650-663`:
```python
def capture_work_liveness(path: Path | str) -> dict:
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return {"path": str(p), "exists": False, "mtime": None, "sha256": None}
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {
        "path": str(p), "exists": True,
        "mtime": stat.st_mtime, "sha256": h.hexdigest(),
    }
```
Both `mtime` (line 661) and `sha256` (line 662) are computed and returned together in a
single dict on every call — the function itself does not implement any partial/lazy
capture.

**However, `capture_work_liveness` has zero call sites anywhere in `src/`** (confirmed by
grep across `src/`: the only occurrence is its own `def` at line 650). Its own preceding
comment (lines 644-649) is explicit: *"LAYER 2 (Group-S witness helper, built now, not
called against StockPhotoAgent this phase)... a second, orthogonal discriminator, not a
replacement for Layer 1."* The "valid orphan claim requires BOTH layers positive" rule
the task asks to find enforced in code does **not exist in `src/`** — it exists only as a
manually-followed checklist in `docs/15-item9-outcome-matrix.md` §6 ("Group S's planned
witness sequence"): *"An ambiguous result on only one layer... is a STOP, not an orphan
claim — both layers must agree"* — a human/harness-side procedural rule, not a code
`assert`/`if` anywhere in `claude_headless.py`, `reconciler.py`, or `bindings.py`. `NEXT.md`
(session-31 follow-up) independently confirms this remains unexercised in practice: *"Layer-2
`capture_work_liveness` movement-across-kill: still OPEN — the snapshot mechanism itself
works... but no pre/post-kill content delta was ever observed across three attempts."*

**Proposed fix:** none proposed — this is a documentation-vs-code gap flag, not
necessarily a defect (the project may intend Layer 2 to remain a manual/harness-side
witness rather than an automated gate). Recording it precisely so it is not mistaken for
an enforced invariant in future audits.

---

### B4 — is the shim's `child_pid` still treated as a liveness signal anywhere?

**VERIFIED — yes, and it is the production liveness signal.** See **B-CRIT-1** above,
which is this exact question answered in full with line citations. `is_execution_alive`
(`claude_headless.py:409-423`), used by both `reap_orphans()` and `recover()`'s check 1 in
every real invocation, is built entirely on `_alive_by_record` against the recorded
`proc.pid` from `subprocess.Popen(argv, ...)` — the `claude.CMD` shim on Windows — with no
descendant-walking. The Layer-1 fix that *would* resolve this (`_resolve_leaf_worker`) is
wired only into the `ITEM9_SENTINEL`-gated test/witness path, never into the production
decision function. **This is the check the module's own docstring calls "structurally
unfalsifiable," and it is still the one production code runs.**

---

## 4. Tier C findings — engine, config, external contracts

### C1 | VERIFIED | `src/runtime/engine/claude_headless.py:242-272` (`_command`)

```python
249        argv = [
250            self._claude_exe, "-p",
251            "--output-format", "stream-json", "--verbose",
252            "--no-session-persistence",
253            "--permission-mode", _DEFAULT_PERMISSION_MODE,
...
265            "--setting-sources", "",
266            # variadic flag: consumes tokens until the next "--flag", so it must
267            # precede --model (which follows and re-anchors the parser).
268            "--disallowedTools", *_DENY_TOOLS,
269        ]
```
`--setting-sources ""` (line 265) is present as a distinct pair of argv elements — the ADR-22
A-empty mechanism — and is placed *before* the variadic `--disallowedTools` so it cannot be
swallowed. Confirmed additionally by `tests/unit/test_engine_adr22.py:45-56`
(`test_command_carries_setting_sources_empty`), which asserts `argv[i+1] == ""` and
`argv[i+1:i+2] == [""]` (a real element, not a dropped token).

---

### C2 | VERIFIED | Single spawn site for the billable `claude` binary; hygiene applied

Full grep of `subprocess.Popen`/`subprocess.run` across `src/` (9 call sites total):

| Site | What it spawns | Env hygiene needed? | Applied? |
|---|---|---|---|
| `claude_headless.py:296` | `claude -p ...` — the ONLY billable engine spawn | Yes | `env=self._hygienic_env()` (line 297) — YES |
| `claude_headless.py:472` | `powershell.exe` (CIM process-table query, `_all_pid_ppid_pairs`) | No — read-only OS query | N/A |
| `claude_headless.py:610` | `sys.executable -c <hold_script>` — inert polling loop, test-only, `ITEM9_SENTINEL` only | No billing risk (no `claude` call) | inherits `os.environ` unfiltered (no `env=` kwarg) — see note below |
| `claude_headless.py:674` | `taskkill` (Windows) | No | N/A |
| `claude_headless.py:689` | `tasklist` | No | N/A |
| `claude_headless.py:696` | `ps` (POSIX) | No | N/A |
| `validation/runner.py:128` | target repo's configured test command | ADR-23, separate hygiene layer | YES — `env=self._child_env()` (line 131) |
| `config.py:163` | `git rev-parse --verify` (branch-existence check) | No | N/A |
| `repo/git_adapter.py:56` | all git plumbing, via `_git()` | No (git itself is not billed) | N/A |

**Only one spawn site invokes the actual `claude` binary** (`claude_headless.py:296`), and
it is the only one that needs ADR-18 hygiene; it has it. **No unguarded `claude` spawn site
exists.** The one item worth flagging: `hold_proc` (line 610) does not pass `env=`, so it
inherits the parent orchestrator's *entire* environment unfiltered, including
`ANTHROPIC_API_KEY` if it happened to be set on the operator's shell — but `hold_proc` never
calls `claude` or makes any network call (it is a pure `while` loop polling a local file's
existence), so this is not a billing leak; noted for completeness only, not as a Tier C
violation.

---

### C3 | VERIFIED (config); UNWITNESSED (live run header) — reviewer model tag

**Where specified:** `config.yaml:44-45` / `config.example.yaml:21-22`:
```yaml
reviewer:
  provider: qwen
  qwen:
    endpoint: 'http://localhost:11434'
    model: qwen2.5-coder:14b     # VERIFIED present at this endpoint
```
Pinned in config, not in code — `src/runtime/reviewer/qwen_ollama.py`'s `QwenOllamaReviewer`
takes `model` as a constructor argument (`__init__`, lines 48-59) supplied by
`main.py:106-108`'s `_make_reviewer` reading `cfg.reviewer.qwen.model` — no hardcoded model
string anywhere in `src/`. Config-only, correctly.

**Is the resolved tag written into any run header or event log?** **No.** `loop.py:289-293`
and `loop.py:295-301` (`ReviewApproved`/`ReviewRejected` payloads) carry only
`"reviewer_provider": verdict.provider` — and `ReviewVerdict.provider` is set to the
literal string `self.name` = `"qwen"` (`reviewer/qwen_ollama.py:45,141-148` — the class
constant, not the specific model tag). The model string `qwen2.5-coder:14b` never appears
in any event payload, `ExecutionRecord`, or printed run header anywhere in `src/`. This
matches the task's **KNOWN RESIDUAL** exactly as stated ("Reviewer model-tag pin never
witnessed in a live run header. Expected.") — confirmed present, unchanged, not re-litigated
further.

---

### C4 | VERIFIED — no hardcoded absolute path/port/machine assumption in `src/`

Grep for `C:\Projects`, `localhost:11434`, `127.0.0.1` across `src/`: **zero matches.** Every
repository path, branch, and reviewer endpoint reaches `src/` exclusively through
`config.Config` (`config.py`), matching ADR-20's "repository is configuration only" rule and
`CLAUDE.md`'s "never hardcode a repo path... anywhere in src/". The only absolute
machine-specific paths in the entire tracked tree live in `config.yaml`/`config.example.yaml`
(`C:\Projects\StockPhotoAgent`, `C:\Python314\python.exe`) — config, exactly where the rule
says they belong — and in test fixtures (`tmp_path`, standard pytest idiom, not a
machine-specific hardcode).

---

### C5 | VERIFIED — `HISTORIAN_SWEEP_ACTIVE` present; CLI version pin **stale in code comments**

`HISTORIAN_SWEEP_ACTIVE` (ADR-22 Option B) is present, config-driven, exactly as designed:
`config.yaml:34-40`:
```yaml
  child_env:                     # ADR-22 B layer (belt-and-braces beside the
    HISTORIAN_SWEEP_ACTIVE: '1'  # argv --setting-sources ""); sunset only when...
```
merged in `_hygienic_env()` (`claude_headless.py:224`, `env.update(self.cfg.child_env)`,
applied **before** the ADR-18 strip so the strip always wins — confirmed by
`test_engine_adr22.py:70-84`, `test_child_env_cannot_override_strip_list`).

**Current pinned CLI version, and where checked — VERIFIED as a docstring/comment-only
"pin" (no code enforces a specific version), and this comment is stale relative to the
project's own later evidence:**
`claude_headless.py:12-14`:
```
VERIFIED CLI contract (claude 2.1.207, Windows, 2026-07-11; re-verified at
2.1.211 on 2026-07-16 — see the ADR-21 fence block below and doc 14 §2 —
re-pin on upgrade):
```
No code anywhere checks `claude --version` against this string — it is a documentation
convention only ("re-witness on upgrade," per the "Upgrade re-pin discipline" in `docs/08`
§5c). `NEXT.md` §4 records a *later* re-probe passing at CLI **2.1.220** (Session 18,
2026-07-26): *"Re-witnessed at CLI 2.1.220, Session 18 (2026-07-26) — literal §2.4 Probe
2/3 re-run, both PASS."* **The code comment at `claude_headless.py:12-14` was never updated
to reflect the 2.1.220 re-pin** — it still names 2.1.207/2.1.211 as the most recent
verified versions, three CLI bumps stale relative to the project's own `NEXT.md` record.
This is a Tier D4 (docs/code disagreement) finding as much as a Tier C5 one — flagged here
since C5 asked for it directly.

**Proposed fix (NOT applied):**
```diff
--- a/src/runtime/engine/claude_headless.py
+++ b/src/runtime/engine/claude_headless.py
@@ -10,8 +10,8 @@
 VERIFIED CLI contract (claude 2.1.207, Windows, 2026-07-11; re-verified at
-2.1.211 on 2026-07-16 — see the ADR-21 fence block below and doc 14 §2 —
-re-pin on upgrade):
+2.1.211 on 2026-07-16, and again at 2.1.220 on 2026-07-26 (NEXT.md §4,
+"STANDING TICKLE... fired, PASS") — see the ADR-21 fence block below and
+doc 14 §2 — re-pin on upgrade):
```

---

## 5. Tier D findings — hygiene

### D1 | VERIFIED — broad `except` audit

Grep for `except:` and `except Exception` across `src/`: **exactly one hit, and it is
narrow, justified, and non-swallowing.**
`config.py:141-144`:
```python
    try:
        return Config.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise ConfigError(f"{p}: {e}") from e
```
This catches pydantic's `ValidationError` (a type pydantic itself does not guarantee a
stable import path for across versions, hence the broad `Exception` with an explanatory
comment) and immediately **re-raises** as `ConfigError` with the original exception chained
(`from e`) — nothing is swallowed; the process still fails loudly. No bare `except:` exists
anywhere in `src/`. **Clean.**

### D2 — dead code / unreachable branches / no-caller functions

- `capture_work_liveness` (`claude_headless.py:650`) — zero callers in `src/` (see B3).
  Not dead in the sense of unreachable, but currently unused production code, by the
  module's own admission ("built now, not called").
- `EventType.HUMAN_INTERVENTION` / `GUIDELINE_PROMOTED` — declared, never emitted, no
  handler (see A2). Same class: present, currently unreachable via any code path in `src/`.
- No unreachable `if`/`else` branches or functions with zero callers were found among the
  27 `src/` modules beyond the two items above — every other function traced back to at
  least one call site in `src/` or a test.

### D3 — TODO/FIXME/XXX/HACK

```
$ git ls-files "*.py" | Select-String -Pattern "TODO|FIXME|XXX|HACK"
(no matches)
```
**Zero occurrences across all 44 tracked `.py` files.** Nothing to assess for liveness.

### D4 — docs/code disagreement

- **C5 above**: `claude_headless.py:12-14`'s CLI-version comment is stale (2.1.211) relative
  to `NEXT.md`'s later 2.1.220 re-pin record. Doc (`NEXT.md`, the more current source) wins
  per `CLAUDE.md`'s doc-03-wins rule generalized to "most current record wins" for
  non-frozen-contract facts; code comment should be updated, not the other way round.
- **A3 above**: the task's own prompt asserted an ordering ("dirty-workspace... before any
  orphan recovery") that the code does not implement; code and doc 03's actual ordering law
  ("residue preserved... `ExecutionCrashed` emitted... then reset") are mutually consistent
  with each other, so this is a premise-vs-code mismatch in the audit brief, not a
  code-vs-doc-03 conflict — recorded under A3, not re-listed as a new D4 item.
- No other event/state-semantics conflict between doc 03 and the implementation was found;
  `docs/10-reconciliation-report.md` (read in full) documents the original reconciliation
  and its listed divergences (all doc-09-vs-doc-03, already resolved in code); the
  current `events/schema.py`/`state/transitions.py` pair matches doc 03 verbatim on every
  point checked (event type strings, state names, transition table shape).

---

## 6. Known residuals — status confirmed

- **`config.yaml` `project.name`:** task expected `"StockAgent"` vs. repo `StockPhotoAgent`.
  **STATUS: NOT PRESENT — already fixed.** `config.yaml:4` and `config.example.yaml:4` both
  read `name: StockPhotoAgent`, matching the actual directory name. Confirmed via
  `docs/handoffs/HANDOFF_2026-08-02_session28-config-name-mismatch-closed.md` (read in
  full): the rename landed in commit `4afdb4a`, session 28, one session before the range
  most of this review's Pass-5 reading covers. **Do not report this as newly discovered —
  it is resolved, not a residual any longer, and this correction is recorded per the task's
  explicit instruction to confirm-not-relitigate.** (The residual's *origin* — `doc
  08`'s §6 reference `config.yaml` example, which still literally reads `name: StockAgent`
  at line 445 — remains, but that document is a historical Session-0 reference block, not
  the live config; not treated as a live residual.)
- **Reviewer model-tag pin never witnessed in a live run header.** CONFIRMED still true —
  see Tier C3 above. Config carries `qwen2.5-coder:14b`; no event/log path ever writes the
  resolved tag anywhere. Expected, per the task; not re-litigated further.
- **Vacuity-guard detectability: permanently NOT-OBSERVABLE.** Not re-litigated. `NEXT.md`
  §5 ("Vacuity-guard detectability — permanently unproven") and `docs/08` §5c both carry
  this status already; nothing in this session's reading contradicts or adds to it.

---

## 7. Verdict per tier

- **Tier A — 5 findings — weakest evidence level: VERIFIED.** (A-CRIT-1, A1, A2, A3, A4, A5
  are all VERIFIED by direct source reading; none required INFERRED reasoning. Counted as 6
  distinct findings total: A-CRIT-1 plus A1-A5.)
- **Tier B — 5 findings — weakest evidence level: INFERRED** (B1's production-inertness
  claim and B2's "every exit path that leaves it running" both rest partly on the absence of
  a counter-example across a manual trace of `claude_headless.py`, not an exhaustive
  runtime-behavior proof; B-CRIT-1 and B4 are VERIFIED by direct code reading; B3 is
  VERIFIED-by-absence (grep) for the "no code enforces the AND" half, INFERRED for "this is
  by design vs. an oversight.")
- **Tier C — 5 findings — weakest evidence level: UNWITNESSED** (C3's "never witnessed in a
  live run header" is UNWITNESSED by definition — no live run was executed this session,
  per the hard constraint; C1/C2/C4/C5 are VERIFIED by static reading).
- **Tier D — 4 findings — weakest evidence level: VERIFIED** (D1 clean-audit VERIFIED; D2
  and D4 VERIFIED by direct reading and grep; D3 VERIFIED-empty).

---

## 8. Checks run and found CLEAN

- **A1** (fsync-before-advance) — ran, clean, no violating path found.
- **A4** (double-commit guard uses content check, not cardinality) — ran, clean, both call
  sites use `find_merge_commit`/`is_ancestor`.
- **A5** (execution-scoped GC) — ran, clean, matches ADR-15 Amendment 1 exactly.
- **C1** (`--setting-sources ""`) — ran, clean, present and correctly positioned.
- **C2** (ANTHROPIC_API_KEY popped on every `claude` spawn) — ran, clean, single spawn site,
  hygienic.
- **C4** (no hardcoded path/port in `src/`) — ran, clean, zero matches.
- **D1** (broad `except`) — ran, clean, one narrow justified instance, nothing swallowed.
- **D3** (TODO/FIXME/XXX/HACK) — ran, clean, zero matches.
- **Doc 03 vs. code event/state semantics** (D4's core question) — ran (cross-checked
  `events/schema.py`, `state/transitions.py`, `state/model.py` against doc 03 §§1-3
  verbatim) — clean, no conflict found beyond the version-comment staleness already noted.

**NOT RUN this pass (declared, with reason):**
- **Full line-by-line read of `docs/14-session6-phase2-gate.md`** (1351 lines) — NOT RUN.
  Reason: single largest remaining doc in the corpus; its material conclusions (ADR-22
  probe results, CLI re-pin history, vacuity-guard non-reproduction) are independently
  re-surfaced and cross-checked via `docs/08`, `docs/12`, and `NEXT.md`, all of which were
  read in full and are more current. Time-boxed out of this pass; see coverage ledger.
- **31 of 36 `docs/handoffs/HANDOFF_*.md` files, `docs/handoffs/next-md-archive-2026-07-26.md`
  (773 lines), and both `docs/scratch/*.md` files (993 lines combined)** — NOT RUN. Reason:
  declared partial coverage per the task's own explicit allowance; these are session-by-
  session narrative logs, low-blast-radius per `CLAUDE.md`'s own effort-sizing rule (docs /
  handoffs / scratch work), and `NEXT.md` (read in full, and itself stating "Session-by-
  session narrative & evidence... superseded/closed items" live in the archive) already
  surfaces every still-open item from that corpus. The 5 handoffs most directly bearing on
  Tier A/B findings (sessions 25, 26, 28, 29, 30 — hold_pid landing, config-name fix,
  ADR-19 close) **were** read in full and are cited above.
- **Live-run verification of anything** (C2's transcript check, C3's live header,
  B1-B4's actual runtime behavior beyond static code reading) — NOT RUN, per the hard
  constraint: no `cmd_run` against StockPhotoAgent, no crash harness execution, this
  session.
