import assert from "node:assert/strict";

// Minimal self-contained DOM shim (no dependency install -- the JS-contract
// harness runs this file with plain `node`). Supports exactly what `el()`
// (dom.js), `renderBarChart` (chart.js), and the runs cost <dd> helper touch.
class FakeNode {
  constructor(tag, ns) {
    this.tagName = (tag || "").toUpperCase();
    this.namespaceURI = ns || null;
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
  append(...cs) { for (const c of cs) this.appendChild(c); }
  removeChild(c) { this.childNodes = this.childNodes.filter((x) => x !== c); return c; }
  get firstChild() { return this.childNodes[0] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType !== 3); }
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
  createElementNS: (ns, t) => new FakeNode(t, ns),
  createTextNode: (v) => new FakeText(v),
  body: new FakeNode("body"),
  activeElement: null,
};

const { renderBarChart, chartValueText } = await import(
  "../../../src/draindeck_dashboard/static/js/components/chart.js");
const { buildTopCostChartEntries } = await import(
  "../../../src/draindeck_dashboard/static/js/pages/home.js");
const { runProxyCostDd } = await import(
  "../../../src/draindeck_dashboard/static/js/pages/runs.js");

let count = 0;
function test(name, fn) { fn(); count += 1; }

function collectByClass(node, cls, acc = []) {
  if (node.getAttribute && node.getAttribute("class") === cls) acc.push(node.textContent);
  for (const c of node.childNodes || []) collectByClass(c, cls, acc);
  return acc;
}
function findChip(node, acc = []) {
  const cls = node.getAttribute && node.getAttribute("class");
  if (cls && /\bchip\b/.test(cls)) acc.push(node.textContent);
  if (node.className && /\bchip\b/.test(node.className)) acc.push(node.textContent);
  for (const c of node.childNodes || []) findChip(c, acc);
  return acc;
}

// --- Finding A: chart value labels must show formatted USD, never raw micro-USD ---

test("chartValueText prefers entry.valueText, falls back to String(value)", () => {
  assert.equal(chartValueText({ value: 2340000, valueText: "$2.34" }), "$2.34");
  assert.equal(chartValueText({ value: 7 }), "7"); // count-charts (no valueText) unchanged
});

test("renderBarChart renders valueText as the visible value label, not raw micro-USD", () => {
  const container = new FakeNode("div");
  renderBarChart(container, {
    title: "Top-cost issues",
    entries: [
      { label: "i-complete", value: 2340000, valueText: "$2.34" },
      { label: "i-partial", value: 920000, valueText: "$0.92 observed" },
      { label: "i-zero", value: 0, valueText: "$0.00" },
    ],
  });
  const labels = collectByClass(container, "chart-value-label");
  assert.deepEqual(labels, ["$2.34", "$0.92 observed", "$0.00"]);
  // The raw micro-USD integer must never appear as a value label.
  assert.ok(!labels.includes("2340000"));
});

test("renderBarChart without valueText (count chart) still shows the numeric value", () => {
  const container = new FakeNode("div");
  renderBarChart(container, {
    title: "Issues by state",
    entries: [{ label: "DONE", value: 3 }, { label: "PENDING", value: 1 }],
  });
  assert.deepEqual(collectByClass(container, "chart-value-label"), ["3", "1"]);
});

test("buildTopCostChartEntries formats valueText via proxyCostText, keeps micro-USD as bar value", () => {
  const entries = buildTopCostChartEntries([
    { issueId: "i-complete", proxyCost: { completeness: "COMPLETE", observedMicroUsd: 2340000 } },
    { issueId: "i-partial", proxyCost: { completeness: "PARTIAL", observedMicroUsd: 920000 } },
    { issueId: "i-zero", proxyCost: { completeness: "COMPLETE", observedMicroUsd: 0 } },
  ]);
  assert.deepEqual(entries.map((e) => e.valueText), ["$2.34", "$0.92 observed", "$0.00"]);
  assert.deepEqual(entries.map((e) => e.value), [2340000, 920000, 0]); // magnitude preserved for geometry
  assert.deepEqual(entries.map((e) => e.label), ["i-complete", "i-partial", "i-zero"]);
});

test("buildTopCostChartEntries tolerates an empty/absent list", () => {
  assert.deepEqual(buildTopCostChartEntries([]), []);
  assert.deepEqual(buildTopCostChartEntries(undefined), []);
});

// --- Finding B: Run Detail must show the visible Partial label when PARTIAL ---

test("runProxyCostDd appends a visible Partial chip when completeness is PARTIAL", () => {
  const dd = runProxyCostDd({
    completeness: "PARTIAL", observedMicroUsd: 920000,
    meteredExecutions: 1, totalExecutions: 2,
  });
  assert.ok(/\$0\.92 observed/.test(dd.textContent));
  assert.ok(/1 of 2 executions metered/.test(dd.textContent));
  assert.deepEqual(findChip(dd), ["Partial"]);
});

test("runProxyCostDd shows no Partial chip when COMPLETE", () => {
  const dd = runProxyCostDd({
    completeness: "COMPLETE", observedMicroUsd: 2340000,
    meteredExecutions: 2, totalExecutions: 2,
  });
  assert.ok(/\$2\.34/.test(dd.textContent));
  assert.deepEqual(findChip(dd), []);
});

test("runProxyCostDd shows no Partial chip when UNAVAILABLE", () => {
  const dd = runProxyCostDd({
    completeness: "UNAVAILABLE", observedMicroUsd: null,
    meteredExecutions: 0, totalExecutions: 1,
  });
  assert.ok(/Not observed/.test(dd.textContent));
  assert.deepEqual(findChip(dd), []);
});

console.log(`proxy_cost_render.js: ${count} test(s) passed`);
