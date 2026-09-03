import assert from "node:assert/strict";
import {
  isCancellable, CANCEL_DIALOG_COPY, RESUME_DIALOG_COPY, isQueuePaused, resumeStatusText,
} from "../../../src/draindeck_dashboard/static/js/pages/run-control.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

// RED J-1: only a QUEUED command is cancellable; every other status is not.
test("isCancellable is true only for QUEUED", () => {
  assert.equal(isCancellable({ status: "QUEUED" }), true);
  assert.equal(isCancellable({ status: "CLAIMED" }), false);
  assert.equal(isCancellable({ status: "LAUNCHED" }), false);
  assert.equal(isCancellable({ status: "LAUNCH_OWNERSHIP_UNKNOWN" }), false);
  assert.equal(isCancellable({ status: "ABNORMAL_EXIT" }), false);
  assert.equal(isCancellable({ status: "ACKNOWLEDGED" }), false);
  assert.equal(isCancellable({ status: "COMPLETED" }), false);
  assert.equal(isCancellable({ status: "REFUSED" }), false);
  assert.equal(isCancellable({ status: "CANCELLED" }), false);
  assert.equal(isCancellable(null), false);
});

// RED J-2: the confirmation copy makes the safety contract explicit -- it
// removes only the waiting batch, never touches a running process, and does
// not alter runtime events.
test("cancel dialog copy states waiting-batch-only, no running process, no events", () => {
  assert.match(CANCEL_DIALOG_COPY, /waiting/i);
  assert.match(CANCEL_DIALOG_COPY, /running process/i);
  assert.match(CANCEL_DIALOG_COPY, /runtime event/i);
});

// RED J-3: cancel copy now also states the remaining queue is paused until Resume.
test("cancel dialog copy states the queue is paused until resume", () => {
  assert.match(CANCEL_DIALOG_COPY, /paus/i);
  assert.match(CANCEL_DIALOG_COPY, /resume/i);
});

// RED J-4: resume copy states resuming permits the next waiting command to start.
test("resume dialog copy states next waiting command may start", () => {
  assert.match(RESUME_DIALOG_COPY, /resum/i);
  assert.match(RESUME_DIALOG_COPY, /next|waiting/i);
  assert.match(RESUME_DIALOG_COPY, /start|launch|run/i);
});

// RED J-5: isQueuePaused reflects the queue response's paused flag only.
test("isQueuePaused is true only when the queue response is paused", () => {
  assert.equal(isQueuePaused({ queuePaused: true }), true);
  assert.equal(isQueuePaused({ queuePaused: false }), false);
  assert.equal(isQueuePaused({}), false);
  assert.equal(isQueuePaused(null), false);
});

// RED J-6: resume copy states a dirty target defers execution and preserves commands.
test("resume dialog copy states dirty defers and preserves waiting commands", () => {
  assert.match(RESUME_DIALOG_COPY, /dirty|clean/i);
  assert.match(RESUME_DIALOG_COPY, /defer|preserv|stay|remain|queued/i);
});

// RED J-7: resumeStatusText explains deferred progression, or null when not deferred.
test("resumeStatusText returns a deferred message only when progression is deferred", () => {
  const deferred = resumeStatusText({ progressionDeferred: true });
  assert.match(deferred, /defer/i);
  assert.match(deferred, /clean/i);
  assert.match(deferred, /queued|waiting|preserv/i);
  assert.equal(resumeStatusText({ progressionDeferred: false }), null);
  assert.equal(resumeStatusText(null), null);
});

console.log(`run-control cancel UI: ${count} test(s) passed`);
