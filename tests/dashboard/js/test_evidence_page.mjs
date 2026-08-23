import assert from "node:assert/strict";
import { parseEvidenceQuery } from "../../../src/draindeck_dashboard/static/js/pages/evidence.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("defaults: no keyset bounds, direction desc (newest first)", () => {
  const q = parseEvidenceQuery(new URLSearchParams(""));
  assert.equal(q.beforeEvidenceId, null);
  assert.equal(q.afterEvidenceId, null);
  assert.equal(q.direction, "desc");
});

test("parses integer keyset bounds", () => {
  const q = parseEvidenceQuery(new URLSearchParams("beforeEvidenceId=42&afterEvidenceId=10"));
  assert.equal(q.beforeEvidenceId, 42);
  assert.equal(q.afterEvidenceId, 10);
});

test("invalid keyset values are ignored, never NaN", () => {
  const q = parseEvidenceQuery(new URLSearchParams("beforeEvidenceId=notanumber"));
  assert.equal(q.beforeEvidenceId, null);
});

test("direction only accepts asc explicitly, everything else is desc", () => {
  assert.equal(parseEvidenceQuery(new URLSearchParams("direction=asc")).direction, "asc");
  assert.equal(parseEvidenceQuery(new URLSearchParams("direction=bogus")).direction, "desc");
});

console.log(`evidence.js: ${count} test(s) passed`);
