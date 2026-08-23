// Unit 7 (docs/27 SS9.1/SS13.3): plain-Node unit tests for the pure
// functions in static/js/format.js -- "the current lightweight test
// approach", no new production dependency (no Jest/Vitest). Run directly
// via `node tests/dashboard/js/test_format.mjs`; exits non-zero (and
// prints which assertion failed) on any failure, so
// tests/dashboard/test_static_js_contracts.py can drive it as a
// subprocess and assert on the exit code.
import assert from "node:assert/strict";
import {
  availabilityLabel, displayName, formatAbsoluteTimestamp, formatRelativeTime,
  inconsistencyLabel, NO_CONTROLLED_FINISH_TEXT, NOT_YET_OBSERVED_TEXT,
  offsetToPage, pageToOffset, runDisplayOutcome, runMetadataText, severityRank,
} from "../../../src/draindeck_dashboard/static/js/format.js";

let count = 0;
function test(name, fn) {
  fn();
  count += 1;
}

test("displayName strips windows and posix separators", () => {
  assert.equal(displayName("C:\\Projects\\StockPhotoAgent"), "StockPhotoAgent");
  assert.equal(displayName("/home/user/myrepo"), "myrepo");
  assert.equal(displayName("C:\\Projects\\StockPhotoAgent\\"), "StockPhotoAgent");
  assert.equal(displayName(""), "");
});

test("availabilityLabel maps exactly, null means not yet observed", () => {
  assert.equal(availabilityLabel("AVAILABLE"), "Available");
  assert.equal(availabilityLabel("OFFLINE"), "Offline");
  assert.equal(availabilityLabel(null), NOT_YET_OBSERVED_TEXT);
  assert.equal(availabilityLabel(undefined), NOT_YET_OBSERVED_TEXT);
});

test("runDisplayOutcome never renders Running/Active", () => {
  assert.equal(runDisplayOutcome(null), NO_CONTROLLED_FINISH_TEXT);
  assert.equal(runDisplayOutcome("COMPLETED"), "COMPLETED");
  assert.ok(!runDisplayOutcome(null).toLowerCase().includes("running"));
});

test("inconsistencyLabel never says verified/valid", () => {
  assert.equal(inconsistencyLabel(false), "No inconsistency observed");
  assert.equal(inconsistencyLabel(true), "Inconsistency observed");
  assert.ok(!inconsistencyLabel(false).toLowerCase().includes("verified"));
});

test("runMetadataText uses the exact legacy fallback text", () => {
  assert.equal(runMetadataText(null), "run metadata unavailable (legacy/ambiguous)");
  assert.equal(runMetadataText({ available: false, message: "custom" }), "custom");
  const text = runMetadataText({
    available: true, engineProvider: "anthropic", engineModel: "claude", outcome: "COMPLETED",
  });
  assert.equal(text, "anthropic / claude — COMPLETED");
});

test("severityRank orders critical before warning before information", () => {
  assert.ok(severityRank("critical") < severityRank("warning"));
  assert.ok(severityRank("warning") < severityRank("information"));
});

test("page/offset mapping round-trips", () => {
  assert.equal(pageToOffset(1, 50), 0);
  assert.equal(pageToOffset(3, 50), 100);
  assert.equal(offsetToPage(100, 50), 3);
  assert.equal(offsetToPage(0, 50), 1);
});

test("formatAbsoluteTimestamp returns null for invalid input, a string for valid", () => {
  assert.equal(formatAbsoluteTimestamp(""), null);
  assert.equal(formatAbsoluteTimestamp("not-a-date"), null);
  assert.equal(typeof formatAbsoluteTimestamp("2026-08-23T00:00:00Z"), "string");
});

test("formatRelativeTime never appears without a valid source timestamp", () => {
  assert.equal(formatRelativeTime("", Date.now()), null);
  const now = Date.parse("2026-08-23T00:10:00Z");
  assert.equal(formatRelativeTime("2026-08-23T00:09:58Z", now), "just now");
  assert.equal(formatRelativeTime("2026-08-23T00:05:00Z", now), "5m ago");
});

console.log(`format.js: ${count} test(s) passed`);
