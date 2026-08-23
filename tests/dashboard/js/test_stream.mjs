import assert from "node:assert/strict";
import {
  connectionStatusLabel, CONNECTION_STATUS, createChangeCoalescer, createPeriodicRefresh,
  isSystemWideChange, SYSTEM_REPOSITORY_ID,
} from "../../../src/draindeck_dashboard/static/js/stream.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }
async function asyncTest(name, fn) { await fn(); count += 1; }

test("connectionStatusLabel: exact wording, never claims a process is running", () => {
  assert.equal(connectionStatusLabel(CONNECTION_STATUS.CONNECTED), "Updates connected");
  assert.equal(connectionStatusLabel(CONNECTION_STATUS.CONNECTING), "Connecting to updates");
  assert.equal(connectionStatusLabel(CONNECTION_STATUS.RECONNECTING), "Reconnecting to updates");
  assert.equal(connectionStatusLabel(CONNECTION_STATUS.RESYNCING), "Refreshing snapshot");
  for (const status of Object.values(CONNECTION_STATUS)) {
    assert.ok(!connectionStatusLabel(status).toLowerCase().includes("running"));
  }
});

test("SYSTEM_REPOSITORY_ID is the reserved value 0, real repos start at 1", () => {
  assert.equal(SYSTEM_REPOSITORY_ID, 0);
  assert.equal(isSystemWideChange({ repositoryId: 0 }), true);
  assert.equal(isSystemWideChange({ repositoryId: 1 }), false);
});

await asyncTest("coalescer: a burst of changes to the SAME identity fires once with the latest", async () => {
  const flushes = [];
  const coalescer = createChangeCoalescer((changes) => flushes.push(changes), 10);
  coalescer.push({ repositoryId: 1, entityType: "issue", entityId: "42", rev: 1 });
  coalescer.push({ repositoryId: 1, entityType: "issue", entityId: "42", rev: 2 });
  coalescer.push({ repositoryId: 1, entityType: "issue", entityId: "42", rev: 3 });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(flushes.length, 1);
  assert.equal(flushes[0].length, 1);
  assert.equal(flushes[0][0].rev, 3); // latest wins, not a queue of all three
});

await asyncTest("coalescer: different identities in the same window all survive", async () => {
  const flushes = [];
  const coalescer = createChangeCoalescer((changes) => flushes.push(changes), 10);
  coalescer.push({ repositoryId: 1, entityType: "issue", entityId: "42" });
  coalescer.push({ repositoryId: 1, entityType: "issue", entityId: "43" });
  coalescer.push({ repositoryId: SYSTEM_REPOSITORY_ID, entityType: "attention", entityId: null });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(flushes.length, 1);
  assert.equal(flushes[0].length, 3);
});

await asyncTest("coalescer: system repositoryId 0 and repository-scoped entity are distinct keys", async () => {
  const flushes = [];
  const coalescer = createChangeCoalescer((changes) => flushes.push(changes), 10);
  coalescer.push({ repositoryId: SYSTEM_REPOSITORY_ID, entityType: "read_model", entityId: null });
  coalescer.push({ repositoryId: SYSTEM_REPOSITORY_ID, entityType: "repository_health", entityId: null });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(flushes[0].length, 2);
});

await asyncTest("periodic refresh fires on the given interval and stop() ends it", async () => {
  let ticks = 0;
  const handle = createPeriodicRefresh(() => { ticks += 1; }, 15);
  await new Promise((resolve) => setTimeout(resolve, 50));
  handle.stop();
  const afterStop = ticks;
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.ok(ticks >= 2, `expected at least 2 ticks, got ${ticks}`);
  assert.equal(ticks, afterStop); // no further ticks after stop()
});

console.log(`stream.js: ${count} test(s) passed`);
