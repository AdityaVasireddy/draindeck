import assert from "node:assert/strict";
import {
  noRunSummaryText, planRefusalLines, queueModeSummaryText, queueStatusText,
} from "../../../src/draindeck_dashboard/static/js/pages/run-control.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("empty selection produces exactly one line", () => {
  const lines = planRefusalLines({ ok: false, emptySelection: true });
  assert.deepEqual(lines, ["No issues are selected."]);
});

test("every unknown id is reported, not just the first", () => {
  const lines = planRefusalLines({ ok: false, unknownIds: ["ghost1", "ghost2"] });
  assert.ok(lines.some((l) => l.includes("ghost1")));
  assert.ok(lines.some((l) => l.includes("ghost2")));
  assert.equal(lines.length, 2);
});

test("every blocker names issue, dependency, and dependency state", () => {
  const lines = planRefusalLines({
    ok: false,
    blockers: [
      { issueId: "a", missingDependencyId: "d1", dependencyState: "PENDING" },
      { issueId: "b", missingDependencyId: "d2", dependencyState: "NEEDS_HUMAN" },
    ],
  });
  assert.equal(lines.length, 2);
  assert.ok(lines[0].includes("a") && lines[0].includes("d1") && lines[0].includes("PENDING"));
  assert.ok(lines[1].includes("b") && lines[1].includes("d2") && lines[1].includes("NEEDS_HUMAN"));
});

test("terminal-selected, cycle, and omitted-active are all reported together", () => {
  const lines = planRefusalLines({
    ok: false,
    terminalSelected: [{ issueId: "a", state: "DONE" }],
    cycleMembers: ["x", "y"],
    omittedActiveIds: ["z"],
  });
  assert.equal(lines.length, 3);
  assert.ok(lines.some((l) => l.includes("a") && l.includes("DONE")));
  assert.ok(lines.some((l) => l.includes("x") && l.includes("y")));
  assert.ok(lines.some((l) => l.includes("z")));
});

// Live-browser regression (Unit 8 evidence): a run-all command with no
// issueIds rendered the literal text "ALLnull" because a ternary `null`
// was passed to the native Element.append(), which stringifies non-Node
// arguments -- String(null) === "null". Caught live, fixed by extracting
// the summary text into these pure functions.
test("a run-all command's summary text never contains the literal 'null'", () => {
  const text = queueModeSummaryText({ mode: "ALL", issueIds: null });
  assert.equal(text, "ALL");
  assert.ok(!text.includes("null"));
});

test("a selected command's summary text lists its issue ids", () => {
  const text = queueModeSummaryText({ mode: "SELECTED", issueIds: ["a", "b"] });
  assert.equal(text, "SELECTED: a, b");
});

test("queue status text shows FIFO position only while genuinely QUEUED", () => {
  assert.equal(queueStatusText({ status: "QUEUED", queuePosition: 3 }), "QUEUED (position 3)");
  assert.equal(queueStatusText({ status: "LAUNCHED", queuePosition: null }), "LAUNCHED");
});

// ADR-30 review blocker 1: process exit is not runtime batch completion --
// COMPLETED (a process-exit-0 fact) must never be shown as if it were the
// runtime's own outcome; the confirmed, event-derived outcome (or its
// honest absence) is what actually gets displayed.
test("an exit-0 process with a confirmed INTERRUPTED outcome is not shown as completed", () => {
  const text = queueStatusText({ status: "COMPLETED", runtimeOutcome: "INTERRUPTED" });
  assert.ok(text.includes("INTERRUPTED"));
  assert.ok(!text.includes("Completed") && !text.toLowerCase().includes("success"));
});

test("an exit-0 process with no confirmed correlation is not shown as completed", () => {
  const text = queueStatusText({ status: "COMPLETED", runtimeOutcome: null });
  assert.ok(text.includes("no controlled finish observed"));
  assert.ok(!text.includes("Completed"));
});

test("an exit-0 process with a confirmed COMPLETED outcome displays it correctly", () => {
  const text = queueStatusText({ status: "COMPLETED", runtimeOutcome: "COMPLETED" });
  assert.ok(text.includes("COMPLETED"));
});

test("a non-COMPLETED queue status (e.g. ABNORMAL_EXIT) is unaffected", () => {
  assert.equal(queueStatusText({ status: "ABNORMAL_EXIT", queuePosition: null }), "ABNORMAL_EXIT");
});

// ADR-30 review finding 9: an explicit, accessible no-op message instead of
// silently returning to an unchanged "No run commands yet." queue view.
test("no-run summary names the terminal count when issues exist", () => {
  const text = noRunSummaryText({ totalTerminalCount: 8 });
  assert.equal(text, "Nothing to run; 8 issues are already terminal.");
});

test("no-run summary uses singular phrasing for exactly one terminal issue", () => {
  const text = noRunSummaryText({ totalTerminalCount: 1 });
  assert.equal(text, "Nothing to run; 1 issue is already terminal.");
});

test("no-run summary handles a genuinely empty configured file", () => {
  const text = noRunSummaryText({ totalTerminalCount: 0 });
  assert.equal(text, "Nothing to run; no issues are configured.");
});

console.log(`run-control.js: ${count} test(s) passed`);
