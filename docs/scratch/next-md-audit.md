# NEXT.md audit — Phase 0 + Phase 1 (inventory only, no edits made)

## Phase 0 — Preconditions

**0a. Restore point.** `git status --porcelain -- NEXT.md` → empty (clean). `git log -1 --oneline -- NEXT.md` →
**`d239471 session 17: Dry-run A PASS -- gate (b) loop-composition variable collapsed`**. This SHA was
independently observed this session (not assumed from the prompt); it matches the prompt's expected ref.
**This is the restore point.**

**0b. Must-survive presence check** (grepped this session, line numbers as currently in NEXT.md):
- (a) vacuity-guard detectability question (permanently UNPROVEN): **PRESENT at L277-279** — "Still UNPROVEN,
  untouched, carried into smoke labeled per standing ruling: the vacuity-guard detectability question (three
  independent non-reproductions, positive control never fired)."
- (b) three carried-unwitnessed surfaces (Session 17): **PRESENT at L269-276** — main.py end-to-end startup
  composition (L271-274), orphan-crash recovery path (L275), real-tree behavior (L276).
- (c) CLI-2.1.214 tickle (doc 14 §2.4 Probe 2/3 re-probes): **PRESENT at L203-204** — "Standing tickle: doc 14
  §2.4 Probe 2/3 two-leg re-probes at CLI 2.1.214 — untouched."

All three items are PRESENT. No ABSENT items to report as a gap.

**0c. Archive durability ack.** Understood: if content is moved from tracked NEXT.md into an untracked archive
file, that is a durability regression (an untracked-only copy of removed history) until the trim and the
archive land in the **same commit**. No commit will be made in this task. The exact atomic commit set is named
at the end of Phase 4 (not reached yet — Phase 1 stops below for go-ahead).

---

## Phase 1 — Inventory

NEXT.md is currently **938 lines**. The table below tiles L1–L938 completely: 41 rows, contiguous, no gaps,
no overlaps (verified boundary-by-boundary while building the table).

Redundancy checks personally performed this session (Hard Rule 1): read `docs/14-session6-phase2-gate.md` in
full (1–1068) and `docs/08-session-0-closure-and-adr-amendments.md` §5b–§5d (L95–234) and §5c (L123–144) this
session. Anything not checked against a personally-read target this session is marked UNIQUE, per the rule
("unread = UNIQUE"), even where a plausible duplicate is suspected.

| # | Lines | ~L | Content class | Destination | Redundancy | Supersession cite (DEAD only) | Anchor token |
|---|---|---|---|---|---|---|---|
| 1 | 1-2 | 2 | SESSION-NARRATIVE | KEEP-IN-NEXT | UNIQUE | — | `# NEXT` |
| 2 | 3-14 | 12 | TICKLE | KEEP-IN-NEXT | UNIQUE | — | `STANDING TICKLE — check on every claude CLI version bump` |
| 3 | 15-30 | 16 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:980-1061 (§2.7, same Session-12 CLI-2.1.215 re-probe, doc14 has full fidelity) | — | `re-run COMPLETE, GREEN — see doc 14 §2.7` |
| 4 | 31-59 | 29 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:542-704 (§2.6 Session-9 vacuity finding) + doc14:894-977 (Session-11 pointer) | — | `re-run attempted, PARTIAL — see doc 14 §2.6` |
| 5 | 60-71 | 12 | DECISION-RECORD | ARCHIVE | UNIQUE — doc14 only *references* this NEXT.md-named gap (doc14:836-840 says "Per NEXT.md's already-open VACUITY-GUARD GAP…"); the gap framing itself originates here, not there | — | `no longer discriminates: it comes back clean regardless of suppression` |
| 6 | 72-85 | 14 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:817-869 (§2.6 Item-0 Pass-2 positive control) | — | `third independent data point, still not resolved` |
| 7 | 86-109 | 24 | DECISION-RECORD | ARCHIVE | UNIQUE — options (a)/(b) framing not restated in doc14; doc14 only records the outcome (§2.7-adjacent) | — | `re-establish a discriminating control` |
| 8 | 110-143 | 34 | EVIDENCE | DELETE | DUPLICATE-VERIFIED — doc14:894-938 (Session-11 Step B/C, matching pid/marker/cwd details) | — | `Option (a) BUILT and RUN — control restored` |
| 9 | 144-161 | 18 | EVIDENCE | DELETE | DUPLICATE-VERIFIED — doc14:939-953 (personally read and compared this session; near-identical "both halves" text) | — | `What this establishes, and what it does not` |
| 10 | 162-168 | 7 | DECISION-RECORD | DELETE | DUPLICATE-VERIFIED — doc14:955-960 | — | `Decision recorded: Option (a) chosen over Option (b)` |
| 11 | 169-218 | 50 | EVIDENCE / GATE | ARCHIVE | UNIQUE — doc14 stops at §2.7 (Session 12); no Session-16 content exists there. A handoff for this session exists (`HANDOFF_2026-07-26_step3-precondition4-mutation-leg-closure.md`) but was not read this session, so no duplicate claim is made | — | `Precondition roll-up: 1 MET, 2 CLOSED, 3 CLOSED, 4 CLOSED, 5 MET` |
| 12 | 219-265 | 47 | EVIDENCE | ARCHIVE | UNIQUE — doc14 has no Session-17 content. `HANDOFF_2026-07-26_session17-dryrun-a-pass-correction-note.md` was read this session and explicitly defers to NEXT.md for full cycle-by-cycle evidence ("Full detail in NEXT.md's Session 17 entry") — i.e. NEXT.md is the higher-fidelity copy, not a duplicate of the handoff | — | `Three cycles run 1→2→4 via explicit step() calls` |
| 13 | 266-284 | 19 | GATE | KEEP-IN-NEXT | UNIQUE — this is the must-survive block (0b items a and b) | — | `main.py's end-to-end startup composition` |
| 14 | 285-305 | 21 | DECISION-RECORD | ARCHIVE | UNIQUE (same handoff-defers-to-NEXT.md reasoning as row 12) | — | `Correction note (Session 17, 2026-07-26)` |
| 15 | 306-379 | 74 | EVIDENCE / DECISION-RECORD | DELETE | DUPLICATE-VERIFIED — docs/08:226-234 ("Phase 2 status note (Session 15…)" — 112/112, 60/60 both seeds, VIRTUAL_ENV-absent witness, the three-part-AND deferral, "git stash… does NOT satisfy this" all present verbatim in substance) | — | `ValidationCfg.env: dict[str, str \| None] in src/runtime/config.py` |
| 16 | 380-441 | 62 | DECISION-RECORD | DELETE | DUPLICATE-VERIFIED — docs/08:176-224 (§5d: ACCEPTED status, problem, decision rules 1-3, options A-F, escalation trigger, sequencing, gate chain — all present) | — | `ADR-23 ACCEPTED (docs/08 §5d) — validation-command toolchain resolution` |
| 17 | 442-476 | 35 | EVIDENCE | ARCHIVE | UNIQUE — docs/08 §5d does not cover Issues.md location/format; not found in doc14 either | — | `Issues.md authored in StockAgent at the correct location` |
| 18 | 477-520 | 44 | DECISION-RECORD | KEEP-IN-NEXT | UNIQUE — still OPEN, decision needed (not resolved anywhere) | — | `Ingest does not verify/enforce checked-out branch before reading Issues.md` |
| 19 | 521-547 | 27 | EVIDENCE | ARCHIVE | UNIQUE — not in doc14 (post-dates §2.7 narrowly; doc14's own tail at L1050-1060 records the *error* being corrected, not this session's *fix*) | — | `reviewer.qwen.model reinstated to qwen2.5-coder:14b` |
| 20 | 548-564 | 17 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:980-1061 (§2.7) | — | `ADR-22 STANDING TICKLE re-probe RUN and GREEN at CLI 2.1.215` |
| 21 | 565-580 | 16 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:894-977 | — | `synthetic positive control for ADR-22 BUILT and RUN` |
| 22 | 581-599 | 19 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:780-869 | — | `Item 0 RUN (not just designed) — see doc 14 §2.6` |
| 23 | 600-618 | 19 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:542-704 | — | `claude CLI version witnessed = 2.1.212 (bumped from 2.1.211)` |
| 24 | 619-626 | 8 | DECISION-RECORD | DELETE | DUPLICATE-DEGRADED — doc14:396-401, 1064-1068 | — | `ADR-22 marked Accepted (doc 08 §5c) and its mechanism landed` |
| 25 | 627-669 | 43 | EVIDENCE | DELETE | DUPLICATE-VERIFIED — doc14:403-490 (code changes, two-leg argv survival) + doc14:492-530 (106 unit, 60/60 both seeds) | — | `106 passed, identity-confirmed (not just arithmetic)` |
| 26 | 670-672 | 3 | DECISION-RECORD | DELETE | DUPLICATE-VERIFIED — doc14:532-538 | — | `Step 3 unblock criteria (from NEXT.md's earlier wording) — SATISFIED` |
| 27 | 673-759 | 87 | PRECONDITION | KEEP-IN-NEXT (condensed) | MIXED — base Session-9 evidence for items 0-5 is DUPLICATE-VERIFIED against doc14:871-890, but the block is overlaid with Session 12-14 status updates (item 2 closed, item 3 closed, item 1 partial-fix) that have **no** counterpart in doc14 (frozen at §2.7) — those overlay portions are UNIQUE. Not splittable cleanly without breaking the live status table; flagged for Phase 2 discussion rather than force-split here | — | `Step 3's OWN separate preconditions — checked LIVE Session 9` |
| 28 | 760-764 | 5 | EVIDENCE | DELETE | DUPLICATE-VERIFIED — doc14:881-884 | — | `C:\Projects\StockPhotoAgent matches config.yaml → project.repository exactly` |
| 29 | 765-770 | 6 | DECISION-RECORD | ARCHIVE | DUPLICATE-DEGRADED — doc14:886-890 (close paraphrase, not exact) | — | `Do NOT mark Step 3 planned or begin planning it` |
| 30 | 771-785 | 15 | DECISION-RECORD | ARCHIVE | UNIQUE | — | `UPDATE (Session 14, 2026-07-25). Item counts above are stale` |
| 31 | 786-803 | 18 | DECISION-RECORD | ARCHIVE | UNIQUE | — | `UPDATE 2 (Session 14, continued, 2026-07-25)` |
| 32 | 804-813 | 10 | EVIDENCE | DELETE | DUPLICATE-DEGRADED — doc14:210-287 (§2.1/§2.2) | — | `2a billing — split still PAUSED (Help Center art. 15036540` |
| 33 | 814-846 | 33 | DECISION-RECORD / EVIDENCE | DELETE | DUPLICATE-VERIFIED — docs/08:127-129 (§5c, item-1 knowledge-contamination) + docs/08:108-119 (§5b Amendment 1, including the "QUEUED PREREQUISITE" init-manifest text, matched near-verbatim) | — | `structured init-manifest capture. Mechanism TBD` |
| 34 | 847-865 | 19 | EVIDENCE | DELETE | DUPLICATE-VERIFIED — doc14:15-192 (§0/§1/§1.5) | — | `Isolated mutation spot-check (gutting reset_hard in bindings.py:102` |
| 35 | 866-873 | 8 | SESSION-NARRATIVE | ARCHIVE | UNIQUE — doc 13 not read this session; unread = UNIQUE per Hard Rule 1 | — | `the orchestrator loop is real: main.py run --config config.yaml` |
| 36 | 874-883 | 10 | DECISION-RECORD | DELETE | DUPLICATE-VERIFIED — docs/08:95-106 (ADR-21 decision text: `--allowedTools` falsified, denylist fence, accepted deviation — matched closely) | — | `a live probe FALSIFIED the plan's --allowedTools fence` |
| 37 | 884-896 | 13 | EVIDENCE | ARCHIVE | UNIQUE — doc 13 not read this session (this looks like Session-5/6 baseline evidence, predating doc14's own Step-0 baseline numbers, which differ) | — | `103/103 unit (74 prior + 29 new: engine fence ×2` |
| 38 | 897-905 | 9 | GATE / ACTION | KEEP-IN-NEXT | UNIQUE — operational verify commands, current | — | `Durability gate: python tests\crash\harness.py %TEMP%\ch (expect 60` |
| 39 | 906-920 | 15 | PRECONDITION | KEEP-IN-NEXT | UNIQUE | — | `NEEDS USER INPUT before the first real StockAgent run (doc 13 §6)` |
| 40 | 921-928 | 8 | ACTION | — | see row 41 note | pending | `Harness follow-up: add the two deferred crash points` |
| 41 | 929-938 | 10 | ACTION | DELETE (929-934) / KEEP-IN-NEXT (935-938) | MIXED — L929-934 ("Next: gated live smoke — BLOCKED on the knowledge/-contamination ADR decision") is DEAD, self-superseded within this same file: **cite NEXT.md:619-626 ("Item 1 — CLOSED (Session 8, 2026-07-16/17)")** and NEXT.md:169-218 (Step-3 preconditions now all MET/CLOSED as of Session 16), both read this session. L935-938 ("Then 5 real StockAgent issues, supervised…", the `--allowedTools` non-goal note) is still-accurate forward plan — UNIQUE, not dead | NEXT.md:619-626 (self-cite, this session) | `Next: gated live smoke — BLOCKED on the knowledge/-contamination ADR` |

**Tiling check:** rows tile L1→L938 with zero gaps and zero overlaps (1-2, 3-14, 15-30, 31-59, 60-71, 72-85,
86-109, 110-143, 144-161, 162-168, 169-218, 219-265, 266-284, 285-305, 306-379, 380-441, 442-476, 477-520,
521-547, 548-564, 565-580, 581-599, 600-618, 619-626, 627-669, 670-672, 673-759, 760-764, 765-770, 771-785,
786-803, 804-813, 814-846, 847-865, 866-873, 874-883, 884-896, 897-905, 906-920, 921-928, 929-938). Final line:
938, matching `wc -l NEXT.md`. **Tiling holds.**

Row 40 was split out of what would otherwise be part of row 41's block purely to isolate the DEAD sub-range
(929-934) from the surrounding still-accurate text (921-928, 935-938) cleanly — row 40 itself (921-928) is a
bullet list of already-struck-through (`~~…~~`) completed items ("DONE" markers already in the text); it is not
dead in the sense of "wrong," it is stale scaffolding around a list whose items are already marked done. Flagged
as a borderline case for Phase 2 discussion, not resolved unilaterally here.

---

## Phase 1.5 — Frozen-doc append surface

**Result: zero frozen-doc appends are indicated.** Every row initially suspected of needing a doc-12-style dated
append (ADR-23 Phase 1/2 narrative, the ADR-21 Amendment-1 queued-prerequisite text, the ADR-21 "big finding")
turned out, on personally reading `docs/08-session-0-closure-and-adr-amendments.md` (§5b L95-119, §5c L123-144,
§5d L176-234) and `docs/14-session6-phase2-gate.md` (full, 1-1068) this session, to **already be present there**
at equal or higher fidelity (rows 15, 16, 33, 36 above). Nothing in the inventory requires writing into doc 14
or any ADR. The only proposed destinations are KEEP-IN-NEXT, ARCHIVE (new file, `docs/handoffs/next-md-archive-
<date>.md`), or DELETE (content fully covered elsewhere, already personally verified).

This is well under the hard threshold (≤2 frozen docs / ≤4 appends) — **no scope-concern stop applies.**

The one known duplicate named in the task prompt (NEXT.md 139-150 ↔ doc14 L939-953) corresponds to row 9 in the
table above (actual boundary read this session: NEXT.md 144-161 ↔ doc14 939-953) — confirmed DUPLICATE-VERIFIED,
appends nowhere, consistent with the prompt's framing.

---

Stopping here per instructions. Awaiting go-ahead on both the inventory table and the (empty) append list before
Phase 2 migration begins.
