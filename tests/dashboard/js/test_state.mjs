import assert from "node:assert/strict";
import {
  createStore, resolveStoredTheme, themeAttributeFor,
} from "../../../src/draindeck_dashboard/static/js/state.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("resolveStoredTheme defaults to system on absence/corruption", () => {
  assert.equal(resolveStoredTheme(null), "system");
  assert.equal(resolveStoredTheme(undefined), "system");
  assert.equal(resolveStoredTheme("garbage"), "system");
  assert.equal(resolveStoredTheme("light"), "light");
  assert.equal(resolveStoredTheme("dark"), "dark");
});

test("themeAttributeFor: system means no data-theme attribute", () => {
  assert.equal(themeAttributeFor("system"), null);
  assert.equal(themeAttributeFor("light"), "light");
  assert.equal(themeAttributeFor("dark"), "dark");
});

test("createStore notifies subscribers and supports functional updates", () => {
  const store = createStore(1);
  const seen = [];
  const unsubscribe = store.subscribe((v) => seen.push(v));
  store.set(2);
  store.set((prev) => prev + 10);
  assert.deepEqual(seen, [2, 12]);
  assert.equal(store.get(), 12);
  unsubscribe();
  store.set(99);
  assert.deepEqual(seen, [2, 12]); // no more notifications after unsubscribe
});

console.log(`state.js: ${count} test(s) passed`);
