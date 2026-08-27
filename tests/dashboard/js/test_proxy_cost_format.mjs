// Unit 5: plain-Node tests for the proxy-cost pure formatters in format.js
// (spec §5). Run via `node tests/dashboard/js/test_proxy_cost_format.mjs`.
import assert from "node:assert/strict";
import {
  averageCostText, coverageText, formatMicroUsd, isPartialCost,
  PROXY_COST_UNAVAILABLE_TEXT, proxyCostText,
} from "../../../src/draindeck_dashboard/static/js/format.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("formatMicroUsd", () => {
  assert.equal(formatMicroUsd(1840000), "$1.84");
  assert.equal(formatMicroUsd(0), "$0.00");
  assert.equal(formatMicroUsd(500000), "$0.50");
  assert.equal(formatMicroUsd(null), null);
  assert.equal(formatMicroUsd(undefined), null);
});

test("proxyCostText complete/partial/unavailable", () => {
  assert.equal(proxyCostText({ completeness: "COMPLETE", observedMicroUsd: 1840000 }), "$1.84");
  assert.equal(proxyCostText({ completeness: "PARTIAL", observedMicroUsd: 1840000 }), "$1.84 observed");
  assert.equal(proxyCostText({ completeness: "UNAVAILABLE", observedMicroUsd: null }),
    PROXY_COST_UNAVAILABLE_TEXT);
  assert.equal(proxyCostText(null), PROXY_COST_UNAVAILABLE_TEXT);
});

test("metered zero shows $0.00 not unavailable", () => {
  assert.equal(proxyCostText({ completeness: "COMPLETE", observedMicroUsd: 0 }), "$0.00");
});

test("isPartialCost", () => {
  assert.equal(isPartialCost({ completeness: "PARTIAL" }), true);
  assert.equal(isPartialCost({ completeness: "COMPLETE" }), false);
  assert.equal(isPartialCost(null), false);
});

test("coverageText", () => {
  assert.equal(coverageText({ meteredExecutions: 2, totalExecutions: 3 }), "2 of 3 executions metered");
  assert.equal(coverageText({ meteredExecutions: 0, totalExecutions: 0 }), "No executions observed");
});

test("averageCostText", () => {
  assert.equal(averageCostText({ observedMicroUsd: 920000, observed: false, completedIssues: 2 }), "$0.92");
  assert.equal(averageCostText({ observedMicroUsd: 920000, observed: true, completedIssues: 2 }),
    "$0.92 observed");
  assert.equal(averageCostText({ observedMicroUsd: null, observed: false, completedIssues: 0 }),
    "No completed issues");
  assert.equal(averageCostText({ observedMicroUsd: null, observed: true, completedIssues: 2 }),
    PROXY_COST_UNAVAILABLE_TEXT);
  assert.equal(averageCostText(null), PROXY_COST_UNAVAILABLE_TEXT);
});

console.log(`ok - ${count} proxy-cost format tests passed`);
