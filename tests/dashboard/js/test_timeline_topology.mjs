import assert from "node:assert/strict";
import { entityUrl } from "../../../src/draindeck_dashboard/static/js/components/timeline-topology.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("entityUrl maps each node kind to its correctly-pluralized detail URL", () => {
  assert.equal(entityUrl(1, { kind: "issue", id: "42" }), "/repositories/1/issues/42");
  assert.equal(entityUrl(1, { kind: "run", id: "run-1" }), "/repositories/1/runs/run-1");
  assert.equal(entityUrl(1, { kind: "execution", id: "42-e1" }), "/repositories/1/executions/42-e1");
  assert.equal(entityUrl(1, { kind: "evidence", id: "7" }), "/repositories/1/evidence/7");
});

console.log(`timeline-topology.js: ${count} test(s) passed`);
