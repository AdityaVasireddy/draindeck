import assert from "node:assert/strict";
import {
  PREFLIGHT_ALERT_COPY, worktreeBlocksRun, isAcknowledgeable, ACK_DIALOG_COPY,
} from "../../../src/draindeck_dashboard/static/js/pages/run-control.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

// RED C-1: the exact preflight alert copy is present and is the required string.
test("preflight alert copy is the exact required string", () => {
  assert.equal(
    PREFLIGHT_ALERT_COPY,
    "Commit or clean all tracked and untracked changes, including Issues.md, before running issues.",
  );
});

// RED C-1: a dirty preflight blocks the run controls; a clean one does not.
test("worktreeBlocksRun is true only when preflight reports not clean", () => {
  assert.equal(worktreeBlocksRun({ clean: false, untrackedCount: 1 }), true);
  assert.equal(worktreeBlocksRun({ clean: true }), false);
  assert.equal(worktreeBlocksRun(null), false);   // no data yet -> advisory only
  assert.equal(worktreeBlocksRun(undefined), false);
});

// RED C-3: only an ABNORMAL_EXIT command is acknowledgeable; ambiguous/other
// blocked commands stay blocked with no acknowledge affordance.
test("isAcknowledgeable is true only for ABNORMAL_EXIT", () => {
  assert.equal(isAcknowledgeable({ status: "ABNORMAL_EXIT" }), true);
  assert.equal(isAcknowledgeable({ status: "LAUNCH_OWNERSHIP_UNKNOWN" }), false);
  assert.equal(isAcknowledgeable({ status: "LAUNCHED" }), false);
  assert.equal(isAcknowledgeable({ status: "QUEUED" }), false);
  assert.equal(isAcknowledgeable({ status: "COMPLETED" }), false);
});

// RED C-4: the confirmation copy makes clear it unlocks only and does not retry.
test("acknowledge dialog copy states unlock-only, no retry", () => {
  assert.match(ACK_DIALOG_COPY, /unlock/i);
  assert.match(ACK_DIALOG_COPY, /not retry|does not retry|no retry/i);
});

console.log(`run-control recovery UI: ${count} test(s) passed`);
