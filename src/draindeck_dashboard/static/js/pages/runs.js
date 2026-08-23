"use strict";
// Runs Explorer and Run Detail (docs/27 SS6.5). The outcome banner uses
// "Observed finish" or "No controlled finish observed" -- never
// "Active"/"Running" (ADR-25 gives Dashboard no liveness signal).
import { ApiError, apiFetch } from "../api.js";
import { renderTimeline, renderTopology } from "../components/timeline-topology.js";
import { clear, el, syncList } from "../dom.js";
import { formatAbsoluteTimestamp, inconsistencyLabel, runDisplayOutcome } from "../format.js";
import {
  isIndexPreparingError, preparingRow, projectionIncompleteBanner, removeReadinessBanner,
  renderPreparingPanel, staleBanner,
} from "../readiness.js";

function outcomeTone(displayOutcome) {
  if (displayOutcome === "COMPLETED") return "ok";
  if (displayOutcome === "no controlled finish observed") return "muted";
  return "danger";
}

export async function render(root, params, ctx) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Runs"]));

  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Runs"]),
    el("thead", null, [
      el("tr", null, [
        el("th", { scope: "col" }, ["Repository"]),
        el("th", { scope: "col" }, ["Run"]),
        el("th", { scope: "col" }, ["Observed start"]),
        el("th", { scope: "col" }, ["Engine"]),
        el("th", { scope: "col" }, ["Reviewer"]),
        el("th", { scope: "col" }, ["Outcome"]),
        el("th", { scope: "col" }, ["Inconsistency"]),
        el("th", { scope: "col" }, ["Last event"]),
      ]),
    ]),
    el("tbody"),
  ]);
  wrapper.appendChild(table);
  root.appendChild(wrapper);

  const repoId = params && params.repoId;
  const tbody = table.querySelector("tbody");
  await loadRuns(root, wrapper, tbody, repoId, ctx);
}

function renderRows(tbody, items) {
  syncList(tbody, items, (run) => `${run.repository.id}:${run.runId}`, (row, run) => {
    clear(row);
    row.append(
      el("td", null, [run.repository.displayName]),
      el("th", { scope: "row" }, [
        el("a", { href: `/repositories/${run.repository.id}/runs/${run.runId}`, className: "row-title" },
          [run.runId]),
      ]),
      el("td", null, [formatAbsoluteTimestamp(run.observedStartedAt) || "not observed"]),
      el("td", null, [run.engineProvider || "unknown"]),
      el("td", null, [run.reviewerProvider || "unknown"]),
      el("td", null, [run.displayOutcome]),
      el("td", null, [inconsistencyLabel(run.inconsistent)]),
      el("td", null, [run.lastEventId != null ? String(run.lastEventId) : "none"]),
    );
  }, el("td", { colspan: "8" }, ["No runs observed yet."]), "tr");
}

async function loadRuns(root, wrapper, tbody, repoId, ctx) {
  const url = repoId ? `/api/runs?repositoryId=${repoId}&limit=100` : "/api/runs?limit=100";
  try {
    const coordinator = ctx && ctx.coordinator;
    const data = coordinator ? await coordinator.fetch("runs:list", url) : await apiFetch(url);
    if (data === undefined) return;
    removeReadinessBanner(root);
    if (data.stale) root.insertBefore(staleBanner(), wrapper);
    else if (data.projectionState && !data.projectionState.complete) {
      root.insertBefore(projectionIncompleteBanner(), wrapper);
    }
    renderRows(tbody, data.items);
  } catch (err) {
    clear(tbody);
    if (isIndexPreparingError(err)) tbody.appendChild(preparingRow(8));
    else tbody.appendChild(el("tr", null, [
      el("td", { colspan: "8", role: "alert" }, [`Could not load runs: ${err.message}`]),
    ]));
  }
}

/** SSE-invalidation path (docs/27 SS9.3): re-fetches and syncList-updates
    only the table body/banner, reusing the mounted shell. */
export async function refresh(root, params, ctx) {
  const wrapper = root.querySelector(".ledger-table-wrapper");
  const tbody = root.querySelector("tbody");
  if (!wrapper || !tbody) { await render(root, params, ctx); return; }
  const repoId = params && params.repoId;
  await loadRuns(root, wrapper, tbody, repoId, ctx);
}

export async function renderDetail(root, params) {
  clear(root);
  const { repoId, runId } = params;
  let run, timeline, topology;
  try {
    [run, timeline, topology] = await Promise.all([
      apiFetch(`/api/repositories/${repoId}/runs/${encodeURIComponent(runId)}`),
      apiFetch(`/api/repositories/${repoId}/runs/${encodeURIComponent(runId)}/timeline?limit=100`),
      apiFetch(`/api/repositories/${repoId}/runs/${encodeURIComponent(runId)}/topology`),
    ]);
  } catch (err) {
    if (isIndexPreparingError(err)) {
      renderPreparingPanel(root);
      return;
    }
    const notFound = err instanceof ApiError && err.status === 404;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" }, [notFound ? "Run not found." : "Could not load this run."]),
    ]));
    return;
  }

  root.appendChild(el("h1", { className: "text-display" }, [run.runId]));
  root.appendChild(el("p", null, [
    el("span", { className: `chip chip--${outcomeTone(run.displayOutcome)}` }, [
      run.outcome ? "Observed finish: " + run.outcome : run.displayOutcome,
    ]),
  ]));

  const identityDl = el("dl", { className: "identity-block" }, [
    el("dt", null, ["Engine"]), el("dd", null, [`${run.engineProvider || "unknown"} / ${run.engineModel || "unknown"}`]),
    el("dt", null, ["Reviewer"]), el("dd", null, [`${run.reviewerProvider || "unknown"} / ${run.reviewerModel || "unknown"}`]),
    el("dt", null, ["Config digest"]), el("dd", { className: "text-mono" }, [run.configDigest || "unavailable"]),
    el("dt", null, ["Observed started"]), el("dd", null, [formatAbsoluteTimestamp(run.observedStartedAt) || "not observed"]),
    el("dt", null, ["Observed finished"]), el("dd", null, [formatAbsoluteTimestamp(run.observedFinishedAt) || "not observed"]),
    el("dt", null, ["Inconsistency"]), el("dd", null, [inconsistencyLabel(run.inconsistent)]),
    el("dt", null, ["Last event"]), el("dd", null, [run.lastEventId != null ? String(run.lastEventId) : "none"]),
  ]);
  root.appendChild(identityDl);

  if (run.budget && Object.keys(run.budget).length > 0) {
    root.appendChild(el("h2", { className: "text-headline" }, ["Configured budget"]));
    const budgetDl = el("dl", { className: "identity-block" });
    for (const [key, value] of Object.entries(run.budget)) {
      budgetDl.appendChild(el("dt", null, [key.replace(/_/g, " ")]));
      budgetDl.appendChild(el("dd", null, [String(value)]));
    }
    root.appendChild(budgetDl);
  }

  root.appendChild(el("h2", { className: "text-headline" }, ["Related entities"]));
  const topologyContainer = el("div", { className: "topology-container" });
  renderTopology(topologyContainer, topology, repoId);
  root.appendChild(topologyContainer);

  root.appendChild(el("h2", { className: "text-headline" }, ["Metadata timeline"]));
  const timelineList = el("ul", { className: "entity-list timeline-list", "aria-label": "Metadata timeline" });
  renderTimeline(timelineList, timeline.items);
  root.appendChild(timelineList);
}
