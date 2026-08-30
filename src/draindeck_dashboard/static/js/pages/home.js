"use strict";
// Operator Home (docs/27 SS6.1): fused cross-repository health and
// current attention, never a marketing tour. Real data only -- no
// illustrative counts.
import { apiFetch } from "../api.js";
import { renderBarChart } from "../components/chart.js";
import { clear, el, statusChip, syncList, text, timeElement } from "../dom.js";
import {
  availabilityLabel, averageCostText, coverageText, displayName, formatAbsoluteTimestamp,
  formatRelativeTime, proxyCostText, runDisplayOutcome,
} from "../format.js";
import { projectionIncompleteBanner } from "../readiness.js";

const _AVAILABILITY_TONE = { AVAILABLE: "ok", EMPTY: "muted", NOT_INITIALIZED: "warn", OFFLINE: "danger" };
const _SEVERITY_TONE = { critical: "danger", warning: "warn", information: "muted" };

/** Pure transform: raw /api/overview + /api/repository-summaries +
    /api/attention + /api/evidence responses -> a plain view-model.
    Node-testable without a DOM. */
export function buildHomeViewModel({ overview, repositorySummaries, attention, recentEvidence }) {
  return {
    hasRepositories: overview.repositories.total > 0,
    repositories: repositorySummaries.items.map((repo) => ({
      id: repo.id,
      displayName: repo.displayName,
      availability: repo.availability,
      attentionCount: repo.attentionCount,
      latestRunDisplayOutcome: repo.latestRun ? runDisplayOutcome(repo.latestRun.outcome) : null,
    })),
    attentionPreview: attention.items.slice(0, 5).map((item) => ({
      conditionId: item.conditionId,
      kind: item.kind,
      severity: item.severity,
      message: item.message,
      targetUrl: item.targetUrl,
      repositoryId: item.repository ? item.repository.id : null,
    })),
    attentionTotal: attention.total,
    recentEvidence: recentEvidence.items.map((item) => ({
      evidenceId: item.evidenceId,
      eventType: item.eventType,
      integrity: item.integrity,
      ts: item.ts,
      repositoryId: item.repository.id,
      repositoryDisplayName: item.repository.displayName,
    })),
    analytics: {
      byAvailability: overview.repositories.byAvailability,
      issuesByState: overview.issues.byState,
      runsByOutcome: overview.runs.byDisplayOutcome,
      evidenceByIntegrity: overview.evidence.byIntegrity,
    },
    // Coding-engine proxy cost (spec §5): total, observed average per completed
    // issue, coverage, and the top-cost issues (chart + accessible table with
    // stable links). Defaults tolerate an older overview payload with no cost.
    proxyCost: {
      total: overview.proxyCost || null,
      average: overview.averageProxyCostPerCompletedIssue || null,
      topCostIssues: (overview.topCostIssues || []).map((i) => ({
        issueId: i.issueId,
        repositoryId: i.repository ? i.repository.id : null,
        repositoryDisplayName: i.repository ? i.repository.displayName : null,
        proxyCost: i.proxyCost,
      })),
    },
    projectionState: overview.projectionState,
  };
}

async function fetchHomeData(coordinator) {
  const [overview, repositorySummaries, attention, recentEvidence] = await Promise.all([
    coordinator ? coordinator.fetch("home:overview", "/api/overview") : apiFetch("/api/overview"),
    coordinator
      ? coordinator.fetch("home:repos", "/api/repository-summaries?limit=50")
      : apiFetch("/api/repository-summaries?limit=50"),
    coordinator
      ? coordinator.fetch("home:attention", "/api/attention?limit=5&status=current")
      : apiFetch("/api/attention?limit=5&status=current"),
    coordinator
      ? coordinator.fetch("home:evidence", "/api/evidence?limit=20&direction=desc")
      : apiFetch("/api/evidence?limit=20&direction=desc"),
  ]);
  return { overview, repositorySummaries, attention, recentEvidence };
}

function renderAnalyticsBand(root, analytics) {
  clear(root);
  const groups = [
    { title: "Repository availability", data: analytics.byAvailability, url: "/repositories" },
    { title: "Issue lifecycle", data: analytics.issuesByState, url: "/issues" },
    { title: "Run outcomes", data: analytics.runsByOutcome, url: "/runs" },
    { title: "Evidence integrity", data: analytics.evidenceByIntegrity, url: "/evidence" },
  ];
  for (const group of groups) {
    const entries = Object.entries(group.data).filter(([, count]) => count > 0);
    const card = el("div", { className: "card analytics-card" });

    if (entries.length === 0) {
      card.appendChild(el("h3", { className: "text-title" }, [group.title]));
      card.appendChild(el("p", { className: "text-muted" }, ["No data observed yet."]));
    } else {
      // The chart is a supplementary visual -- the <dl> beside it is the
      // primary accessible text/table equivalent (DESIGN.md "The Chart
      // Encoding Rule"; docs/27 SS9.4), not the other way around.
      const chartContainer = el("div", { className: "analytics-chart" });
      renderBarChart(chartContainer, {
        title: group.title,
        entries: entries.map(([label, value]) => ({ label, value })),
        basis: "Derived from indexed evidence",
      });
      card.appendChild(chartContainer);

      const list = el("dl", { className: "analytics-dl" });
      for (const [key, count] of entries) {
        list.appendChild(el("dt", null, [key]));
        list.appendChild(el("dd", null, [String(count)]));
      }
      card.appendChild(list);
    }
    card.appendChild(el("a", { href: group.url, className: "btn-ghost" }, ["View all"]));
    root.appendChild(card);
  }
}

/** Top-cost issues -> bar-chart entries. The numeric `value` (micro-USD) drives
    bar geometry; `valueText` is the human-readable proxy-cost label
    ("$2.34" / "$0.92 observed" / "$0.00") so the chart never shows raw
    micro-USD integers. The accessible table below carries full coverage. */
export function buildTopCostChartEntries(topCostIssues) {
  return (topCostIssues || []).map((i) => ({
    label: i.issueId,
    value: (i.proxyCost && i.proxyCost.observedMicroUsd) || 0,
    valueText: proxyCostText(i.proxyCost),
  }));
}

function renderProxyCost(root, proxyCost) {
  clear(root);
  const total = proxyCost.total;
  const summary = el("div", { className: "card" });
  summary.appendChild(el("h3", { className: "text-title" }, ["Total observed proxy cost"]));
  summary.appendChild(el("p", { className: "text-display" }, [proxyCostText(total)]));
  summary.appendChild(el("p", { className: "text-muted" }, [
    total ? coverageText(total) : "No executions observed",
  ]));
  if (total && total.completeness === "PARTIAL") {
    summary.appendChild(statusChip("Partial", "warn"));
  }
  summary.appendChild(el("h3", { className: "text-title" }, ["Observed average per completed issue"]));
  summary.appendChild(el("p", { className: "text-headline" }, [averageCostText(proxyCost.average)]));
  if (proxyCost.average && proxyCost.average.observed) {
    summary.appendChild(statusChip("Observed average", "warn"));
  }
  root.appendChild(summary);

  // Top-cost issues: chart is supplementary; the table below is the primary
  // accessible representation with stable per-issue links (DESIGN.md chart rule).
  const top = proxyCost.topCostIssues;
  const card = el("div", { className: "card" });
  card.appendChild(el("h3", { className: "text-title" }, ["Top-cost issues"]));
  if (!top || top.length === 0) {
    card.appendChild(el("p", { className: "text-muted" }, ["No observed proxy cost yet."]));
    root.appendChild(card);
    return;
  }
  const chartContainer = el("div", { className: "analytics-chart" });
  renderBarChart(chartContainer, {
    title: "Top-cost issues",
    entries: buildTopCostChartEntries(top),
    basis: "Engine-reported API-list-rate proxy",
  });
  card.appendChild(chartContainer);

  const table = el("table", { className: "data-table", "aria-label": "Top-cost issues" });
  const thead = el("thead", null, [el("tr", null, [
    el("th", null, ["Issue"]), el("th", null, ["Repository"]),
    el("th", null, ["Observed proxy cost"]), el("th", null, ["Coverage"]),
  ])]);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const i of top) {
    const link = el("a", { href: `/repositories/${i.repositoryId}/issues/${i.issueId}` }, [i.issueId]);
    tbody.appendChild(el("tr", null, [
      el("td", null, [link]),
      el("td", null, [i.repositoryDisplayName || String(i.repositoryId)]),
      el("td", null, [proxyCostText(i.proxyCost)]),
      el("td", null, [coverageText(i.proxyCost)]),
    ]));
  }
  table.appendChild(tbody);
  card.appendChild(table);
  root.appendChild(card);
}

function renderRepositoryLedger(listEl, repositories) {
  syncList(listEl, repositories, (r) => r.id, (rowEl, repo) => {
    clear(rowEl);
    rowEl.appendChild(el("a", { href: `/repositories/${repo.id}`, className: "row-title" },
      [repo.displayName]));
    const tone = _AVAILABILITY_TONE[repo.availability] || "muted";
    rowEl.appendChild(statusChip(availabilityLabel(repo.availability), tone));
    if (repo.attentionCount > 0) {
      rowEl.appendChild(statusChip(`${repo.attentionCount} attention`, "warn"));
    }
    if (repo.latestRunDisplayOutcome) {
      rowEl.appendChild(el("span", { className: "text-muted" }, [repo.latestRunDisplayOutcome]));
    }
  }, "No repositories registered yet.", "li");
}

function renderAttentionPreview(listEl, items) {
  syncList(listEl, items, (i) => i.conditionId, (rowEl, item) => {
    clear(rowEl);
    const tone = _SEVERITY_TONE[item.severity] || "muted";
    rowEl.appendChild(statusChip(item.severity, tone));
    rowEl.appendChild(el("a", { href: item.targetUrl }, [item.message]));
  }, "No current attention conditions.", "li");
}

function renderRecentActivity(listEl, items) {
  const now = Date.now();
  syncList(listEl, items, (i) => i.evidenceId, (rowEl, item) => {
    clear(rowEl);
    rowEl.appendChild(el("a", { href: `/repositories/${item.repositoryId}/evidence/${item.evidenceId}` },
      [`${item.eventType || "(no type)"} — ${item.repositoryDisplayName}`]));
    rowEl.appendChild(timeElement(item.ts, formatAbsoluteTimestamp(item.ts), formatRelativeTime(item.ts, now)));
  }, "Repositories registered; no data observed yet.", "li");
}

export async function render(root, params, ctx) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Operator Home"]));
  const skeleton = el("p", { className: "skeleton" }, ["Loading overview..."]);
  root.appendChild(skeleton);

  let data;
  try {
    data = await fetchHomeData(ctx && ctx.coordinator);
  } catch (err) {
    if (err === undefined) return; // superseded by a newer navigation
    clear(root);
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" }, ["Could not load the operator overview."]),
      el("p", null, [err.message || String(err)]),
    ]));
    return;
  }
  if (data === undefined) return; // superseded

  const vm = buildHomeViewModel(data);
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Operator Home"]));

  if (!vm.hasRepositories) {
    root.appendChild(el("div", { className: "state-panel" }, [
      el("p", { className: "state-panel-title" }, ["No repositories registered"]),
      el("a", { href: "/repositories/new-target", className: "btn btn-primary" }, ["New target"]),
    ]));
    return;
  }

  if (vm.projectionState && !vm.projectionState.complete) {
    root.appendChild(projectionIncompleteBanner());
  }

  const ledgerSection = el("section", { "aria-labelledby": "home-repos-heading" }, [
    el("h2", { id: "home-repos-heading", className: "text-headline" }, ["Repositories"]),
  ]);
  const ledgerList = el("ul", { className: "entity-list", "aria-label": "Repository ledger" });
  renderRepositoryLedger(ledgerList, vm.repositories);
  ledgerSection.appendChild(ledgerList);
  root.appendChild(ledgerSection);

  const attentionSection = el("section", { "aria-labelledby": "home-attention-heading" }, [
    el("h2", { id: "home-attention-heading", className: "text-headline" }, ["Attention"]),
  ]);
  const attentionList = el("ul", { className: "entity-list", "aria-label": "Current attention" });
  renderAttentionPreview(attentionList, vm.attentionPreview);
  attentionSection.appendChild(attentionList);
  if (vm.attentionTotal > vm.attentionPreview.length) {
    attentionSection.appendChild(el("a", { href: "/attention", className: "btn-ghost" }, ["View all"]));
  }
  root.appendChild(attentionSection);

  const costSection = el("section", { "aria-labelledby": "home-cost-heading" }, [
    el("h2", { id: "home-cost-heading", className: "text-headline" }, ["Proxy cost"]),
  ]);
  const costBand = el("div", { className: "analytics-band", "aria-label": "Proxy cost" });
  renderProxyCost(costBand, vm.proxyCost);
  costSection.appendChild(costBand);
  root.appendChild(costSection);

  const analyticsSection = el("section", { "aria-labelledby": "home-analytics-heading" }, [
    el("h2", { id: "home-analytics-heading", className: "text-headline" }, ["Derived from indexed evidence"]),
  ]);
  const analyticsGrid = el("div", { className: "analytics-band" });
  renderAnalyticsBand(analyticsGrid, vm.analytics);
  analyticsSection.appendChild(analyticsGrid);
  root.appendChild(analyticsSection);

  const activitySection = el("section", { "aria-labelledby": "home-activity-heading" }, [
    el("h2", { id: "home-activity-heading", className: "text-headline" }, ["Recent observed activity"]),
  ]);
  const activityList = el("ul", { className: "entity-list", "aria-label": "Recent observed activity" });
  renderRecentActivity(activityList, vm.recentEvidence);
  activitySection.appendChild(activityList);
  root.appendChild(activitySection);
}

/** SSE-invalidation path (docs/27 SS9.3): reuses the mounted shell's list
    containers and syncList-updates them in place -- never clear(root).
    The repository ledger and attention preview are keyed lists (focus/
    scroll-safe by construction); the analytics band's chart cards are
    rebuilt in place (a much smaller, less common focus target than a
    table row, and not a syncable list). Falls back to a full render()
    if the mounted DOM doesn't match the expected populated shape (e.g.
    hasRepositories flipped since the last render) -- the shell itself
    needs to change in that case, which a partial refresh cannot do. */
export async function refresh(root, params, ctx) {
  const ledgerList = root.querySelector('[aria-label="Repository ledger"]');
  const attentionList = root.querySelector('[aria-label="Current attention"]');
  const costBand = root.querySelector('[aria-label="Proxy cost"]');
  const analyticsGrid = root.querySelector(".analytics-band:not([aria-label='Proxy cost'])")
    || root.querySelectorAll(".analytics-band")[1];
  const activityList = root.querySelector('[aria-label="Recent observed activity"]');
  if (!ledgerList || !attentionList || !costBand || !analyticsGrid || !activityList) {
    await render(root, params, ctx);
    return;
  }

  let data;
  try {
    data = await fetchHomeData(ctx && ctx.coordinator);
  } catch (err) {
    return; // a failed background refresh leaves the last-good view as-is
  }
  if (data === undefined) return; // superseded

  const vm = buildHomeViewModel(data);
  if (!vm.hasRepositories) {
    await render(root, params, ctx);
    return;
  }
  renderRepositoryLedger(ledgerList, vm.repositories);
  renderAttentionPreview(attentionList, vm.attentionPreview);
  renderProxyCost(costBand, vm.proxyCost);
  renderAnalyticsBand(analyticsGrid, vm.analytics);
  renderRecentActivity(activityList, vm.recentEvidence);
}
