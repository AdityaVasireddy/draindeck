"use strict";
// Operator Home (docs/27 SS6.1): fused cross-repository health and
// current attention, never a marketing tour. Real data only -- no
// illustrative counts.
import { apiFetch } from "../api.js";
import { renderBarChart } from "../components/chart.js";
import { clear, el, statusChip, syncList, text, timeElement } from "../dom.js";
import {
  availabilityLabel, displayName, formatAbsoluteTimestamp, formatRelativeTime, runDisplayOutcome,
} from "../format.js";

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
      el("a", { href: "/repositories/new", className: "btn btn-primary" }, ["Add repository"]),
    ]));
    return;
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
