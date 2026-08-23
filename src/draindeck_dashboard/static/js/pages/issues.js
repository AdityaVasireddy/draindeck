"use strict";
// Issues Explorer and Issue Detail (docs/27 SS6.6).
import { ApiError, apiFetch } from "../api.js";
import { renderTimeline, renderTopology } from "../components/timeline-topology.js";
import { clear, el, syncList } from "../dom.js";
import { inconsistencyLabel } from "../format.js";
import {
  isIndexPreparingError, preparingRow, projectionIncompleteBanner, removeReadinessBanner,
  renderPreparingPanel, staleBanner,
} from "../readiness.js";

const _STATE_TONE = {
  DONE: "ok", ACCEPTED: "ok", NEEDS_HUMAN: "danger", REJECTED: "danger", CRASHED: "danger",
  NEEDS_DECOMPOSITION: "warn", PENDING: "muted", ACTIVE: "muted",
};

export async function render(root, params, ctx) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Issues"]));

  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Issues"]),
    el("thead", null, [
      el("tr", null, [
        el("th", { scope: "col" }, ["Repository"]),
        el("th", { scope: "col" }, ["Issue"]),
        el("th", { scope: "col" }, ["Title"]),
        el("th", { scope: "col" }, ["State"]),
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
  await loadIssues(root, wrapper, tbody, repoId, ctx);
}

function renderRows(tbody, items) {
  syncList(tbody, items, (issue) => `${issue.repository.id}:${issue.issueId}`, (row, issue) => {
    clear(row);
    const tone = _STATE_TONE[issue.state] || "muted";
    row.append(
      el("td", null, [issue.repository.displayName]),
      el("th", { scope: "row" }, [
        el("a", { href: `/repositories/${issue.repository.id}/issues/${issue.issueId}`,
                 className: "row-title" }, [issue.issueId]),
      ]),
      el("td", null, [issue.title || ""]),
      el("td", null, [el("span", { className: `chip chip--${tone}` }, [issue.state])]),
      el("td", null, [inconsistencyLabel(issue.inconsistent)]),
      el("td", null, [issue.lastEventId != null ? String(issue.lastEventId) : "none"]),
    );
  }, el("td", { colspan: "6" }, ["No issues observed yet."]), "tr");
}

async function loadIssues(root, wrapper, tbody, repoId, ctx) {
  const url = repoId ? `/api/issues?repositoryId=${repoId}&limit=100` : "/api/issues?limit=100";
  try {
    const coordinator = ctx && ctx.coordinator;
    const data = coordinator ? await coordinator.fetch("issues:list", url) : await apiFetch(url);
    if (data === undefined) return;
    removeReadinessBanner(root);
    if (data.stale) root.insertBefore(staleBanner(), wrapper);
    else if (data.projectionState && !data.projectionState.complete) {
      root.insertBefore(projectionIncompleteBanner(), wrapper);
    }
    renderRows(tbody, data.items);
  } catch (err) {
    clear(tbody);
    if (isIndexPreparingError(err)) tbody.appendChild(preparingRow(6));
    else tbody.appendChild(el("tr", null, [
      el("td", { colspan: "6", role: "alert" }, [`Could not load issues: ${err.message}`]),
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
  await loadIssues(root, wrapper, tbody, repoId, ctx);
}

export async function renderDetail(root, params) {
  clear(root);
  const { repoId, issueId } = params;
  let issue, timeline, topology;
  try {
    [issue, timeline, topology] = await Promise.all([
      apiFetch(`/api/repositories/${repoId}/issues/${encodeURIComponent(issueId)}`),
      apiFetch(`/api/repositories/${repoId}/issues/${encodeURIComponent(issueId)}/timeline?limit=100`),
      apiFetch(`/api/repositories/${repoId}/issues/${encodeURIComponent(issueId)}/topology`),
    ]);
  } catch (err) {
    if (isIndexPreparingError(err)) {
      renderPreparingPanel(root);
      return;
    }
    const notFound = err instanceof ApiError && err.status === 404;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" },
        [notFound ? "Issue not found." : "Could not load this issue."]),
    ]));
    return;
  }

  const tone = _STATE_TONE[issue.state] || "muted";
  root.appendChild(el("h1", { className: "text-display" }, [issue.title || issue.issueId]));
  root.appendChild(el("p", null, [
    el("span", { className: `chip chip--${tone}` }, [issue.state]),
    ` Issue ${issue.issueId} — ${inconsistencyLabel(issue.inconsistent)}`,
  ]));

  root.appendChild(el("h2", { className: "text-headline" }, ["Related entities"]));
  const topologyContainer = el("div", { className: "topology-container" });
  renderTopology(topologyContainer, topology, repoId);
  root.appendChild(topologyContainer);

  root.appendChild(el("h2", { className: "text-headline" }, ["Metadata timeline"]));
  const timelineList = el("ul", { className: "entity-list timeline-list", "aria-label": "Metadata timeline" });
  renderTimeline(timelineList, timeline.items);
  root.appendChild(timelineList);
}
