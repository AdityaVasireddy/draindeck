import assert from "node:assert/strict";
import { capChartEntries, MAX_CHART_CATEGORIES } from
  "../../../src/draindeck_dashboard/static/js/components/chart.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("MAX_CHART_CATEGORIES is exactly 8 (DESIGN.md Chart Encoding Rule)", () => {
  assert.equal(MAX_CHART_CATEGORIES, 8);
});

test("8 or fewer entries pass through unchanged", () => {
  const entries = Array.from({ length: 8 }, (_, i) => ({ label: `c${i}`, value: i + 1 }));
  assert.deepEqual(capChartEntries(entries), entries);
});

test("more than 8 entries collapse the remainder into one 'Other', never dropped", () => {
  const entries = Array.from({ length: 12 }, (_, i) => ({ label: `c${i}`, value: 1 }));
  const capped = capChartEntries(entries);
  assert.equal(capped.length, 8);
  assert.equal(capped[7].label, "Other");
  // The 5 collapsed entries (indices 7-11) sum to 5 -- total value never
  // silently lost, just aggregated.
  assert.equal(capped[7].value, 5);
  const totalBefore = entries.reduce((s, e) => s + e.value, 0);
  const totalAfter = capped.reduce((s, e) => s + e.value, 0);
  assert.equal(totalBefore, totalAfter);
});

test("first 7 entries keep their original order when capping", () => {
  const entries = Array.from({ length: 10 }, (_, i) => ({ label: `c${i}`, value: i }));
  const capped = capChartEntries(entries);
  assert.deepEqual(capped.slice(0, 7).map((e) => e.label), ["c0", "c1", "c2", "c3", "c4", "c5", "c6"]);
});

console.log(`chart.js: ${count} test(s) passed`);
