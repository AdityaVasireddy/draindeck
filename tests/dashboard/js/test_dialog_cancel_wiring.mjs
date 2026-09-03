// RED tests, ULTRA-REVIEW-001 finding 6: Cancel must close both the
// reviewer-model pull confirmation dialog and the equivalent run-control
// "Confirm run" dialog.
//
// Root cause under test: openDialog (components/dialog.js) only invokes a
// button's own onClick -- `if (spec.onClick) spec.onClick();` -- it never
// closes the dialog implicitly. Every OTHER confirmation dialog in this
// codebase (confirmAndAcknowledge, confirmAndCancel, confirmAndResume in
// pages/run-control.js) correctly wires its "Cancel"/"Keep..." button as
// `{ label: "...", className: "btn-ghost", onClick: () => close() }`.
// Exactly two call sites omit it and are therefore inert on Cancel:
//   - components/shell.js `_confirmAndPullReviewerModel`'s "Cancel" button
//     (`{ label: "Cancel", className: "btn-ghost" }`, no onClick)
//   - pages/run-control.js `confirmAndSubmit`'s "Confirm run" dialog's
//     "Cancel" button (same bare shape)
//
// Both dialogs are driven here through their REAL, exported entry points
// (mountLauncherReadiness / render) against a shared minimal DOM shim, so
// this exercises the actual production wiring, not a reconstruction of it.
import assert from "node:assert/strict";
import { installDomShim } from "./dom_shim.mjs";

installDomShim();

let count = 0;
function report(name) { count += 1; console.log(`  ok - ${name}`); }

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function flush() {
  // Lets any already-scheduled microtasks (chained awaits over our
  // synchronously-resolving fetch mocks) drain before the next assertion.
  await new Promise((resolve) => { setTimeout(resolve, 0); });
}

async function testReviewerModelDialogCancelCloses() {
  const shell = await import("../../../src/draindeck_dashboard/static/js/components/shell.js");

  const container = document.createElement("div");
  const coordinator = {
    fetch: async () => ({
      dashboardReady: true, runReady: false, runConfigured: true,
      missing: ["reviewer-model"], model: "qwen2.5-coder", repositoryId: 7,
    }),
  };

  await shell.mountLauncherReadiness(container, { coordinator, repoId: 7 });

  const pullBtn = container.querySelector('[data-action="pull-reviewer-model"]');
  assert.ok(pullBtn, "expected the pull-reviewer-model action button to render");

  pullBtn.click();
  assert.equal(
    document.body.childNodes.length, 1,
    "expected the reviewer-model pull confirmation dialog to open",
  );

  const dialogEl = document.body.childNodes[0];
  const cancelBtn = dialogEl.querySelectorAll("button").find((b) => b.textContent === "Cancel");
  assert.ok(cancelBtn, "expected a 'Cancel' button in the pull-model dialog");

  cancelBtn.click();

  assert.equal(
    document.body.childNodes.length, 0,
    "RED (finding 6): clicking 'Cancel' must close the reviewer-model pull "
    + "confirmation dialog -- src/draindeck_dashboard/static/js/components/"
    + "shell.js:_confirmAndPullReviewerModel's Cancel button has no onClick, "
    + "so the dialog currently stays open.",
  );
  report("reviewer-model dialog: Cancel closes it");
}

async function testRunControlConfirmDialogCancelCloses() {
  const runControl = await import("../../../src/draindeck_dashboard/static/js/pages/run-control.js");
  const repoId = 7;

  const routes = {
    [`GET /api/repositories/${repoId}/configured-issues`]: () => jsonResponse(200, {
      configPath: "/repo/.draindeck/config.local.yaml",
      issuesFilePath: "/repo/Issues.md",
      issuesFileRevision: "abcdef0123456789",
      readModelStatus: "READY",
      parserWarning: false,
      activeIssuesOutsideFile: [],
      budget: null,
      issues: [],
    }),
    [`GET /api/repositories/${repoId}/worktree-preflight`]: () => jsonResponse(200, { clean: true }),
    [`GET /api/repositories/${repoId}/run-commands`]: () => jsonResponse(200, { commands: [], queuePaused: false }),
    [`POST /api/repositories/${repoId}/run-plans`]: () => jsonResponse(200, {
      ok: true, orderedIds: ["ISSUE-1"], excluded: [],
    }),
    [`GET /api/repositories/${repoId}`]: () => jsonResponse(200, { projectPath: "/repo" }),
  };
  globalThis.fetch = async (path, options) => {
    const method = (options && options.method) || "GET";
    const key = `${method} ${path}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unmocked fetch in RED test: ${key}`);
    return handler();
  };

  const root = document.createElement("div");
  await runControl.render(root, { repoId }, {});

  const runAllBtn = root.querySelector("#run-control-run-all");
  assert.ok(runAllBtn, "expected the 'Run all' button to render");
  assert.equal(runAllBtn.disabled, false, "expected 'Run all' to be enabled (clean worktree, READY read model)");

  runAllBtn.click();
  await flush();

  assert.equal(
    document.body.childNodes.length, 1,
    "expected the 'Confirm run' dialog to open after clicking 'Run all'",
  );

  const dialogEl = document.body.childNodes[0];
  const cancelBtn = dialogEl.querySelectorAll("button").find((b) => b.textContent === "Cancel");
  assert.ok(cancelBtn, "expected a 'Cancel' button in the 'Confirm run' dialog");

  cancelBtn.click();

  assert.equal(
    document.body.childNodes.length, 0,
    "RED (finding 6): clicking 'Cancel' must close the run-control 'Confirm run' "
    + "dialog -- src/draindeck_dashboard/static/js/pages/run-control.js:"
    + "confirmAndSubmit's Cancel button has no onClick, so the dialog currently "
    + "stays open (the equivalent of the reviewer-model dialog bug above; this "
    + "file's OTHER three dialogs -- confirmAndAcknowledge, confirmAndCancel, "
    + "confirmAndResume -- already wire onClick: () => close() correctly).",
  );
  report("run-control 'Confirm run' dialog: Cancel closes it");
}

await testReviewerModelDialogCancelCloses();
await testRunControlConfirmDialogCancelCloses();

console.log(`dialog cancel wiring: ${count} test(s) passed`);
