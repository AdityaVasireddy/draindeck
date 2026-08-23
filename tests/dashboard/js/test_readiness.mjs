import assert from "node:assert/strict";
import { ApiError } from "../../../src/draindeck_dashboard/static/js/api.js";
import {
  isIndexPreparingError, PREPARING_TEXT, STALE_TEXT,
} from "../../../src/draindeck_dashboard/static/js/readiness.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("isIndexPreparingError recognizes the exact INDEX_PREPARING code", () => {
  const err = new ApiError("indexed views are still preparing", { code: "INDEX_PREPARING", status: 503 });
  assert.equal(isIndexPreparingError(err), true);
});

test("isIndexPreparingError rejects other ApiError codes", () => {
  const err = new ApiError("not found", { code: "NOT_FOUND", status: 404 });
  assert.equal(isIndexPreparingError(err), false);
});

test("isIndexPreparingError rejects a plain (non-ApiError) error", () => {
  assert.equal(isIndexPreparingError(new Error("boom")), false);
});

test("the exact UI text constants exist and are non-empty", () => {
  assert.ok(PREPARING_TEXT.length > 0);
  assert.ok(STALE_TEXT.length > 0);
});

console.log(`readiness.js: ${count} test(s) passed`);
