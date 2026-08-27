import assert from "node:assert/strict";
import {
  buildAboutFacts, MUTATION_BOUNDARY_TEXT, PROXY_COST_DEFINITION_TEXT,
  PROXY_COST_EXCLUSIONS_TEXT,
} from "../../../src/draindeck_dashboard/static/js/pages/about.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

test("buildAboutFacts orders host, port, database path, and version", () => {
  const facts = buildAboutFacts({ host: "127.0.0.1", port: 8420, dbPath: "C:/x/dashboard.sqlite3", version: "0.1.0" });
  assert.deepEqual(facts.map((f) => f.label), ["Host", "Port", "Database", "Version"]);
  assert.deepEqual(facts.map((f) => f.value), ["127.0.0.1", "8420", "C:/x/dashboard.sqlite3", "0.1.0"]);
});

test("mutation-boundary text is the exact required wording (docs/27 SS6.9)", () => {
  assert.equal(
    MUTATION_BOUNDARY_TEXT,
    "Draindeck Dashboard does not modify registered repositories, event logs, transcripts, diffs, or artifacts. It writes its own local SQLite database for registration and indexed views.",
  );
});

test("proxy-cost definition says proxy not invoice and never $0.00 for missing", () => {
  assert.match(PROXY_COST_DEFINITION_TEXT, /proxy, not an invoice/);
  assert.match(PROXY_COST_DEFINITION_TEXT, /unknown, never as \$0\.00/);
});

test("proxy-cost exclusion list names orchestration and all excluded items", () => {
  for (const term of [/reviewer-LLM cost/, /validation compute/, /orchestration cost/,
    /subscription fees/, /crashed executions/, /Evidence, Search, or Attention/]) {
    assert.match(PROXY_COST_EXCLUSIONS_TEXT, term);
  }
});

console.log(`about.js: ${count} test(s) passed`);
