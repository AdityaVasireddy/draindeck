import assert from "node:assert/strict";

// Minimal self-contained DOM shim (project convention -- see
// test_proxy_cost_render.mjs -- no dependency install; runs under plain
// `node`). Supports exactly what `el()` (dom.js) touches.
class FakeNode {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.nodeType = 1;
    this.childNodes = [];
    this._attrs = {};
    this._text = "";
    this.className = "";
    this.parentNode = null;
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; }
  appendChild(c) { this.childNodes.push(c); c.parentNode = this; return c; }
  set textContent(v) { this._text = String(v); this.childNodes = []; }
  get textContent() {
    if (this.nodeType === 3) return this._text;
    return this._text + this.childNodes.map((c) => c.textContent).join("");
  }
}
class FakeText extends FakeNode {
  constructor(v) { super("#text"); this.nodeType = 3; this._text = String(v); }
}
globalThis.document = {
  createElement: (t) => new FakeNode(t),
  createTextNode: (v) => new FakeText(v),
};

const readiness = await import("../../../src/draindeck_dashboard/static/js/readiness.js");

assert.equal(
  typeof readiness.renderLauncherReadiness,
  "function",
  "RED: missing UI behavior that renders independent Dashboard-ready and Run-ready states",
);

const dashboardOnly = readiness.renderLauncherReadiness({
  dashboardReady: true,
  runReady: false,
});
assert.match(dashboardOnly.textContent, /Dashboard ready/i);
assert.match(dashboardOnly.textContent, /Run not ready/i);

// The symmetric case: Run-ready true while Dashboard is not ready must be
// representable too -- these two facts are independent in both directions
// (docs/32 L-10), never coupled so one implies the other.
const runOnly = readiness.renderLauncherReadiness({
  dashboardReady: false,
  runReady: true,
});
assert.match(runOnly.textContent, /Dashboard not ready/i);
assert.match(runOnly.textContent, /Run ready/i);
assert.doesNotMatch(runOnly.textContent, /Run not ready/i);

// Blocker 3: missing prerequisite names and a clear next action must be
// visible, not just a bare "not ready" chip -- including the specific
// "missing configured reviewer model" case.
const missingModel = readiness.renderLauncherReadiness({
  dashboardReady: true,
  runReady: false,
  missing: ["reviewer-model"],
});
assert.match(missingModel.textContent, /reviewer.model/i);
assert.match(missingModel.textContent, /install|pull|configure/i);

const missingSeveral = readiness.renderLauncherReadiness({
  dashboardReady: true,
  runReady: false,
  missing: ["claude", "ollama"],
});
assert.match(missingSeveral.textContent, /claude/i);
assert.match(missingSeveral.textContent, /ollama/i);

// No missing list at all (e.g. Run-ready true) must show no leftover
// "missing" text from a stale render.
const allReady = readiness.renderLauncherReadiness({ dashboardReady: true, runReady: true, missing: [] });
assert.doesNotMatch(allReady.textContent, /missing/i);

// Pure view-model builder: maps the /api/launcher/readiness JSON response
// shape directly onto renderLauncherReadiness's props, so the fetch/mount
// glue in app.js has nothing left to get wrong beyond calling fetch().
// model/repositoryId pass through (review Blocker 1 follow-up) so the
// pull-model action can name the exact model and know which repository.
assert.equal(typeof readiness.buildLauncherReadinessViewModel, "function");
const vm = readiness.buildLauncherReadinessViewModel({
  dashboardReady: true, runReady: false, missing: ["reviewer-model"], model: "qwen2.5-coder",
  repositoryId: 7,
});
assert.deepEqual(vm, {
  dashboardReady: true, runReady: false, missing: ["reviewer-model"], model: "qwen2.5-coder",
  repositoryId: 7,
});

const vmNoRepo = readiness.buildLauncherReadinessViewModel({
  dashboardReady: true, runReady: false, missing: ["repository-not-selected"],
});
assert.equal(vmNoRepo.model, null);
assert.equal(vmNoRepo.repositoryId, null);

// Blocker 1 follow-up: a missing reviewer model renders an explicit, named,
// confirmable pull action -- not just descriptive text -- when a model is
// known. The actual click/fetch wiring is DOM/fetch-dependent and lives in
// shell.js (verified live in a real browser); here we only prove the
// action is marked in a way that glue code can find and wire up.
const withModelAction = readiness.renderLauncherReadiness({
  dashboardReady: true, runReady: false, missing: ["reviewer-model"], model: "qwen2.5-coder",
});
const pullButtons = withModelAction.childNodes
  .flatMap((n) => n.childNodes || [])
  .flatMap((li) => li.childNodes || [])
  .filter((n) => n.getAttribute && n.getAttribute("data-action") === "pull-reviewer-model");
assert.equal(pullButtons.length, 1, "expected exactly one pull-reviewer-model action button");
assert.equal(pullButtons[0].getAttribute("data-model"), "qwen2.5-coder");
assert.match(pullButtons[0].textContent, /pull.*reviewer model/i);
assert.match(pullButtons[0].textContent, /qwen2\.5-coder/);

// No model known (e.g. reviewer model not configured at all rather than
// merely not pulled) -- no action button is rendered, since there is
// nothing to name or confirm.
const withoutModelAction = readiness.renderLauncherReadiness({
  dashboardReady: true, runReady: false, missing: ["reviewer-model"],
});
const noModelButtons = withoutModelAction.childNodes
  .flatMap((n) => n.childNodes || [])
  .flatMap((li) => li.childNodes || [])
  .filter((n) => n.getAttribute && n.getAttribute("data-action") === "pull-reviewer-model");
assert.equal(noModelButtons.length, 0);

console.log("dashboard_run_readiness_ui.mjs: 9 test(s) passed");
