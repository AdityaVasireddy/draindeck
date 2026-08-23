import assert from "node:assert/strict";
import {
  flattenGroupedResults, nextActiveIndex,
} from "../../../src/draindeck_dashboard/static/js/components/search.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("flattenGroupedResults preserves the fixed 5-group order", () => {
  const flat = flattenGroupedResults({
    evidence: [{ id: "e1" }],
    repositories: [{ id: "r1" }],
    issues: [{ id: "i1" }],
  });
  assert.deepEqual(flat.map((f) => f.group), ["repositories", "issues", "evidence"]);
});

test("flattenGroupedResults tags each item with its group, tolerates missing groups", () => {
  const flat = flattenGroupedResults({ runs: [{ id: "run-1" }] });
  assert.equal(flat.length, 1);
  assert.equal(flat[0].group, "runs");
  assert.equal(flat[0].id, "run-1");
});

test("flattenGroupedResults handles an empty/undefined response gracefully", () => {
  assert.deepEqual(flattenGroupedResults(undefined), []);
  assert.deepEqual(flattenGroupedResults({}), []);
});

test("nextActiveIndex: Down from nothing selected goes to the first item", () => {
  assert.equal(nextActiveIndex(-1, 3, 1), 0);
});

test("nextActiveIndex: Up from nothing selected goes to the last item", () => {
  assert.equal(nextActiveIndex(-1, 3, -1), 2);
});

test("nextActiveIndex wraps at both ends", () => {
  assert.equal(nextActiveIndex(2, 3, 1), 0); // Down past the last wraps to first
  assert.equal(nextActiveIndex(0, 3, -1), 2); // Up past the first wraps to last
});

test("nextActiveIndex with zero results always returns -1 (nothing to select)", () => {
  assert.equal(nextActiveIndex(-1, 0, 1), -1);
  assert.equal(nextActiveIndex(-1, 0, -1), -1);
});

console.log(`search-component.js: ${count} test(s) passed`);
