import assert from "node:assert/strict";
import {
  parseAttentionQuery, STATUS_FILTERS,
} from "../../../src/draindeck_dashboard/static/js/pages/attention.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("defaults to status=current", () => {
  const q = parseAttentionQuery(new URLSearchParams(""));
  assert.equal(q.status, "current");
  assert.equal(q.severity, "");
});

test("accepts resolved and all, rejects unknown values", () => {
  assert.equal(parseAttentionQuery(new URLSearchParams("status=resolved")).status, "resolved");
  assert.equal(parseAttentionQuery(new URLSearchParams("status=all")).status, "all");
  assert.equal(parseAttentionQuery(new URLSearchParams("status=bogus")).status, "current");
});

test("STATUS_FILTERS is exactly current/resolved/all, in that order", () => {
  assert.deepEqual(STATUS_FILTERS.map((f) => f.value), ["current", "resolved", "all"]);
});

test("severity passes through when present", () => {
  assert.equal(parseAttentionQuery(new URLSearchParams("severity=critical")).severity, "critical");
});

console.log(`attention.js: ${count} test(s) passed`);
