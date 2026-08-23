import assert from "node:assert/strict";
import { apiFetch, ApiError, createRequestCoordinator } from
  "../../../src/draindeck_dashboard/static/js/api.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }
async function asyncTest(name, fn) { await fn(); count += 1; }

function fakeResponse({ ok, status, json }) {
  return { ok, status, json: async () => json };
}

await asyncTest("apiFetch returns the parsed body on success", async () => {
  globalThis.fetch = async () => fakeResponse({ ok: true, status: 200, json: { items: [1, 2] } });
  const body = await apiFetch("/api/x");
  assert.deepEqual(body, { items: [1, 2] });
});

await asyncTest("apiFetch throws a typed ApiError with code/status from the error envelope", async () => {
  globalThis.fetch = async () => fakeResponse({
    ok: false, status: 422, json: { error: { code: "INVALID_SORT", message: "bad sort" } },
  });
  await assert.rejects(apiFetch("/api/x"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.code, "INVALID_SORT");
    assert.equal(err.status, 422);
    assert.equal(err.message, "bad sort");
    return true;
  });
});

await asyncTest("apiFetch falls back to a generic message when the body isn't the error envelope", async () => {
  globalThis.fetch = async () => fakeResponse({ ok: false, status: 500, json: null });
  await assert.rejects(apiFetch("/api/x"), (err) => {
    assert.ok(err.message.includes("500"));
    return true;
  });
});

await asyncTest("apiFetch wraps a network failure (fetch itself throwing) as a typed ApiError", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(apiFetch("/api/x"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.code, "NETWORK_ERROR");
    return true;
  });
});

await asyncTest("coordinator: a newer fetch under the same key aborts the older one", async () => {
  const seenSignals = [];
  globalThis.fetch = async (path, options) => {
    seenSignals.push(options.signal);
    await new Promise((resolve) => setTimeout(resolve, 20));
    if (options.signal.aborted) {
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    }
    return fakeResponse({ ok: true, status: 200, json: { path } });
  };
  const coordinator = createRequestCoordinator();
  const first = coordinator.fetch("issues", "/api/issues?page=1");
  const second = coordinator.fetch("issues", "/api/issues?page=2"); // supersedes the first

  const [firstResult, secondResult] = await Promise.all([first, second]);
  assert.equal(firstResult, undefined); // suppressed, not the stale page-1 body
  assert.deepEqual(secondResult, { path: "/api/issues?page=2" });
  assert.ok(seenSignals[0].aborted);
});

await asyncTest("coordinator: different keys never abort each other", async () => {
  globalThis.fetch = async (path, options) => fakeResponse({ ok: true, status: 200, json: { path } });
  const coordinator = createRequestCoordinator();
  const [a, b] = await Promise.all([
    coordinator.fetch("issues", "/api/issues"),
    coordinator.fetch("runs", "/api/runs"),
  ]);
  assert.deepEqual(a, { path: "/api/issues" });
  assert.deepEqual(b, { path: "/api/runs" });
});

await asyncTest("coordinator: abortAll suppresses every in-flight key", async () => {
  globalThis.fetch = async (path, options) => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    if (options.signal.aborted) {
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    }
    return fakeResponse({ ok: true, status: 200, json: {} });
  };
  const coordinator = createRequestCoordinator();
  const p1 = coordinator.fetch("a", "/api/a");
  const p2 = coordinator.fetch("b", "/api/b");
  coordinator.abortAll();
  const [r1, r2] = await Promise.all([p1, p2]);
  assert.equal(r1, undefined);
  assert.equal(r2, undefined);
});

console.log(`api.js: ${count} test(s) passed`);
