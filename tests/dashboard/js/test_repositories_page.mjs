import assert from "node:assert/strict";
import {
  PAGE_SIZE_OPTIONS, parseRegistryQuery, registryQueryToUrl,
} from "../../../src/draindeck_dashboard/static/js/pages/repositories.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("defaults: page 1, first page-size option, ascending name sort", () => {
  const q = parseRegistryQuery(new URLSearchParams(""));
  assert.equal(q.page, 1);
  assert.equal(q.pageSize, PAGE_SIZE_OPTIONS[0]);
  assert.equal(q.sort, "name");
  assert.equal(q.direction, "asc");
  assert.equal(q.q, "");
});

test("invalid/out-of-range page and pageSize fall back to safe defaults", () => {
  assert.equal(parseRegistryQuery(new URLSearchParams("page=abc")).page, 1);
  assert.equal(parseRegistryQuery(new URLSearchParams("page=0")).page, 1);
  assert.equal(parseRegistryQuery(new URLSearchParams("pageSize=999")).pageSize, PAGE_SIZE_OPTIONS[0]);
  assert.equal(parseRegistryQuery(new URLSearchParams("pageSize=100")).pageSize, 100);
});

test("hasAttention parses strictly from the literal string 'true'", () => {
  assert.equal(parseRegistryQuery(new URLSearchParams("hasAttention=true")).hasAttention, true);
  assert.equal(parseRegistryQuery(new URLSearchParams("hasAttention=yes")).hasAttention, false);
  assert.equal(parseRegistryQuery(new URLSearchParams("")).hasAttention, false);
});

test("registryQueryToUrl omits default values, keeping URLs short and stable", () => {
  const url = registryQueryToUrl({
    page: 1, pageSize: PAGE_SIZE_OPTIONS[0], q: "", availability: "", hasAttention: false,
    sort: "name", direction: "asc",
  });
  assert.equal(url, "/repositories");
});

test("registryQueryToUrl round-trips a non-default query", () => {
  const query = {
    page: 3, pageSize: 100, q: "stock", availability: "OFFLINE", hasAttention: true,
    sort: "attentionCount", direction: "desc",
  };
  const url = registryQueryToUrl(query);
  const parsed = parseRegistryQuery(new URLSearchParams(url.split("?")[1]));
  assert.deepEqual(parsed, query);
});

console.log(`repositories.js: ${count} test(s) passed`);
