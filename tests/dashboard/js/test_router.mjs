import assert from "node:assert/strict";
import { createRouter, matchRoute, ROUTES } from "../../../src/draindeck_dashboard/static/js/router.js";

/** Minimal fake document/window implementing only what createRouter uses,
    so the options-threading behavior (Unit 16 fresh-context accessibility
    review: "focus the main heading unless navigation came from a
    same-page filter", docs/27 SS9.2) is Node-testable without a real DOM. */
function _fakeEnv(initialPath) {
  const listeners = { document: {}, window: {} };
  let pathname = initialPath;
  let search = "";
  return {
    documentImpl: {
      addEventListener(type, fn) { listeners.document[type] = fn; },
      removeEventListener(type) { delete listeners.document[type]; },
    },
    windowImpl: {
      location: { get pathname() { return pathname; }, get search() { return search; },
                 get href() { return `http://x${pathname}${search}`; } },
      history: {
        pushState(_state, _title, url) {
          const [p, q] = url.split("?");
          pathname = p; search = q ? `?${q}` : "";
        },
        replaceState(_state, _title, url) {
          const [p, q] = url.split("?");
          pathname = p; search = q ? `?${q}` : "";
        },
      },
      addEventListener(type, fn) { listeners.window[type] = fn; },
      removeEventListener(type) { delete listeners.window[type]; },
    },
  };
}

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("matches the home route exactly, not a prefix", () => {
  assert.deepEqual(matchRoute("/", ROUTES).name, "home");
  assert.equal(matchRoute("/repositories", ROUTES).name, "repositories");
});

test("literal /repositories/new wins over the parameterized :repoId route", () => {
  const match = matchRoute("/repositories/new", ROUTES);
  assert.equal(match.name, "repository-add");
});

test("parameterized routes extract decoded params", () => {
  const match = matchRoute("/repositories/5/issues/issue-42", ROUTES);
  assert.equal(match.name, "issue-detail");
  assert.deepEqual(match.params, { repoId: "5", issueId: "issue-42" });
});

test("URL-encoded path segments are decoded in params", () => {
  const match = matchRoute("/repositories/5/issues/has%20space", ROUTES);
  assert.equal(match.params.issueId, "has space");
});

test("an unknown path returns null, not a false match", () => {
  assert.equal(matchRoute("/this-route-does-not-exist", ROUTES), null);
});

test("every one of the 18 approved server-side UI routes has a client match", () => {
  const serverRoutes = [
    "/", "/repositories", "/repositories/new", "/repositories/5",
    "/repositories/5/runs", "/repositories/5/runs/run-1",
    "/repositories/5/issues", "/repositories/5/issues/42",
    "/repositories/5/executions", "/repositories/5/executions/42-e1",
    "/repositories/5/evidence", "/repositories/5/evidence/7",
    "/attention", "/runs", "/issues", "/executions", "/evidence", "/about",
  ];
  for (const path of serverRoutes) {
    assert.ok(matchRoute(path, ROUTES) !== null, `no client match for ${path}`);
  }
  assert.equal(serverRoutes.length, 18);
});

test("a trailing slash still matches (server and client agree on normalization)", () => {
  assert.ok(matchRoute("/repositories/", ROUTES) !== null);
});

test("navigate() forwards its options object to onNavigate as a third argument", () => {
  const env = _fakeEnv("/attention");
  const calls = [];
  const router = createRouter({ ...env, onNavigate: (match, location, options) => calls.push(options) });
  calls.length = 0; // drop the initial boot dispatch
  router.navigate("/attention?status=resolved", { preserveFocus: true });
  assert.deepEqual(calls, [{ preserveFocus: true }]);
});

test("navigate() with no options forwards undefined (a real navigation, not a same-page filter)", () => {
  const env = _fakeEnv("/attention");
  const calls = [];
  const router = createRouter({ ...env, onNavigate: (match, location, options) => calls.push(options) });
  calls.length = 0;
  router.navigate("/runs");
  assert.deepEqual(calls, [undefined]);
});

test("a same-path navigate() (query-string-only re-dispatch) still forwards options", () => {
  const env = _fakeEnv("/attention");
  const calls = [];
  const router = createRouter({ ...env, onNavigate: (match, location, options) => calls.push(options) });
  calls.length = 0;
  router.navigate("/attention", { preserveFocus: true }); // path === current
  assert.deepEqual(calls, [{ preserveFocus: true }]);
});

console.log(`router.js: ${count} test(s) passed`);
