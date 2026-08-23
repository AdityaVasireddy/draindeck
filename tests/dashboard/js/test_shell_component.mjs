import assert from "node:assert/strict";
import {
  isActiveRoute, RAIL_DESTINATIONS,
} from "../../../src/draindeck_dashboard/static/js/components/shell.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("exactly the eight stable destinations, in order", () => {
  assert.equal(RAIL_DESTINATIONS.length, 8);
  assert.deepEqual(RAIL_DESTINATIONS.map((d) => d.href),
    ["/", "/repositories", "/attention", "/runs", "/issues", "/executions", "/evidence", "/about"]);
  for (const dest of RAIL_DESTINATIONS) {
    assert.ok(dest.label && dest.label.length > 0, `${dest.href} must have a visible label`);
  }
});

test("home is active only at the exact root path", () => {
  assert.equal(isActiveRoute("/", "/"), true);
  assert.equal(isActiveRoute("/repositories", "/"), false);
});

test("a nested detail route activates its section's rail link", () => {
  assert.equal(isActiveRoute("/repositories/5/issues/42", "/issues"), false);
  assert.equal(isActiveRoute("/repositories/5/issues/42", "/repositories"), true);
  assert.equal(isActiveRoute("/attention", "/attention"), true);
});

test("no rail link matches an unrelated route as a substring", () => {
  // "/runs" must not accidentally match "/runsomething"
  assert.equal(isActiveRoute("/runsomething", "/runs"), false);
});

console.log(`shell.js: ${count} test(s) passed`);
