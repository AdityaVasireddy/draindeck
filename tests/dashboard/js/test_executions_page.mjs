import assert from "node:assert/strict";
import { parseGroupBy } from "../../../src/draindeck_dashboard/static/js/pages/executions.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("defaults to execution", () => {
  assert.equal(parseGroupBy(new URLSearchParams("")), "execution");
});

test("accepts issue explicitly", () => {
  assert.equal(parseGroupBy(new URLSearchParams("groupBy=issue")), "issue");
});

test("any other value falls back to execution, never throws", () => {
  assert.equal(parseGroupBy(new URLSearchParams("groupBy=bogus")), "execution");
});

console.log(`executions.js: ${count} test(s) passed`);
