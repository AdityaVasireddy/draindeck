import assert from "node:assert/strict";
import { buildHomeViewModel } from "../../../src/draindeck_dashboard/static/js/pages/home.js";

let count = 0;
function test(name, fn) { fn(); count += 1; }

const baseOverview = {
  repositories: { total: 2, byAvailability: { AVAILABLE: 1, OFFLINE: 1, EMPTY: 0, NOT_INITIALIZED: 0, NOT_OBSERVED: 0 } },
  attention: { current: 1, critical: 0, warning: 1, information: 0 },
  issues: { total: 3, byState: { DONE: 2, PENDING: 1 } },
  runs: { total: 0, byDisplayOutcome: {} },
  executions: { total: 0, byState: {} },
  evidence: { total: 10, byIntegrity: { OK: 10 } },
};

test("hasRepositories reflects overview.repositories.total", () => {
  const vm = buildHomeViewModel({
    overview: baseOverview,
    repositorySummaries: { items: [] }, attention: { items: [], total: 0 },
    recentEvidence: { items: [] },
  });
  assert.equal(vm.hasRepositories, true);

  const emptyVm = buildHomeViewModel({
    overview: { ...baseOverview, repositories: { total: 0, byAvailability: {} } },
    repositorySummaries: { items: [] }, attention: { items: [], total: 0 },
    recentEvidence: { items: [] },
  });
  assert.equal(emptyVm.hasRepositories, false);
});

test("repositories map real fields, never fabricate a latestRun outcome", () => {
  const vm = buildHomeViewModel({
    overview: baseOverview,
    repositorySummaries: {
      items: [
        { id: 1, displayName: "alpha", availability: "AVAILABLE", attentionCount: 0, latestRun: null },
        { id: 2, displayName: "beta", availability: "OFFLINE", attentionCount: 2,
          latestRun: { outcome: "COMPLETED" } },
        { id: 3, displayName: "gamma", availability: "AVAILABLE", attentionCount: 0,
          latestRun: { outcome: null } },
      ],
    },
    attention: { items: [], total: 0 }, recentEvidence: { items: [] },
  });
  assert.equal(vm.repositories[0].latestRunDisplayOutcome, null);
  assert.equal(vm.repositories[1].latestRunDisplayOutcome, "COMPLETED");
  assert.equal(vm.repositories[2].latestRunDisplayOutcome, "no controlled finish observed");
});

test("attentionPreview caps at 5 even if more items are returned, keeps real total", () => {
  const items = Array.from({ length: 8 }, (_, i) => ({
    conditionId: `c${i}`, kind: "ISSUE_NEEDS_HUMAN", severity: "warning", message: "m",
    targetUrl: "/x", repository: { id: 1 },
  }));
  const vm = buildHomeViewModel({
    overview: baseOverview, repositorySummaries: { items: [] },
    attention: { items, total: 28 }, recentEvidence: { items: [] },
  });
  assert.equal(vm.attentionPreview.length, 5);
  assert.equal(vm.attentionTotal, 28);
});

test("recentEvidence maps repository context without exposing payload fields", () => {
  const vm = buildHomeViewModel({
    overview: baseOverview, repositorySummaries: { items: [] }, attention: { items: [], total: 0 },
    recentEvidence: {
      items: [{
        evidenceId: 5, eventType: "IssueCreated", integrity: "OK", ts: "2026-08-23T00:00:00Z",
        repository: { id: 1, displayName: "alpha" }, payload: { secret: true },
      }],
    },
  });
  assert.equal(vm.recentEvidence[0].evidenceId, 5);
  assert.equal(vm.recentEvidence[0].repositoryDisplayName, "alpha");
  assert.ok(!("payload" in vm.recentEvidence[0]));
});

test("analytics band passes through only the real observed counts, no fabricated categories", () => {
  const vm = buildHomeViewModel({
    overview: baseOverview, repositorySummaries: { items: [] }, attention: { items: [], total: 0 },
    recentEvidence: { items: [] },
  });
  assert.deepEqual(vm.analytics.issuesByState, { DONE: 2, PENDING: 1 });
  assert.deepEqual(vm.analytics.evidenceByIntegrity, { OK: 10 });
});

console.log(`home.js: ${count} test(s) passed`);
