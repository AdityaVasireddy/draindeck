"use strict";
// Evidence Explorer and Detail (docs/27 SS6.8). Metadata only -- never
// raw event lines, payload JSON, or a fabricated "CORRUPT" integrity
// badge (corruption is a separate repository-health/attention fact,
// linked to, not shown as an evidence integrity value). Cross-repository
// explorer uses keyset pagination (evidence.id); never a deep OFFSET.
import { ApiError, apiFetch } from "../api.js";
import { clear, el, syncList, timeElement } from "../dom.js";
import { formatAbsoluteTimestamp, formatRelativeTime } from "../format.js";

const _INTEGRITY_TONE = { OK: "ok", TORN: "warn", MALFORMED: "danger", OVERSIZED: "danger" };

/** Pure: parses the explorer's keyset/direction state from a
    URLSearchParams-like object. */
export function parseEvidenceQuery(searchParams) {
  const before = Number.parseInt(searchParams.get("beforeEvidenceId"), 10);
  const after = Number.parseInt(searchParams.get("afterEvidenceId"), 10);
  const direction = searchParams.get("direction");
  return {
    beforeEvidenceId: Number.isFinite(before) ? before : null,
    afterEvidenceId: Number.isFinite(after) ? after : null,
    direction: direction === "asc" ? "asc" : "desc",
  };
}

function buildApiUrl(query, repoId) {
  const params = new URLSearchParams();
  params.set("limit", "50");
  params.set("direction", query.direction);
  if (query.beforeEvidenceId != null) params.set("beforeEvidenceId", String(query.beforeEvidenceId));
  if (query.afterEvidenceId != null) params.set("afterEvidenceId", String(query.afterEvidenceId));
  if (repoId) params.set("repositoryId", String(repoId));
  return `/api/evidence?${params.toString()}`;
}

function renderRows(tbody, items) {
  syncList(tbody, items, (item) => item.evidenceId, (row, item) => {
    clear(row);
    const tone = _INTEGRITY_TONE[item.integrity] || "muted";
    row.append(
      el("th", { scope: "row" }, [
        el("a", { href: `/repositories/${item.repository.id}/evidence/${item.evidenceId}`,
                 className: "row-title text-mono" }, [String(item.evidenceId)]),
      ]),
      el("td", null, [item.repository.displayName]),
      el("td", null, [el("span", { className: `chip chip--${tone}` }, [item.integrity])]),
      el("td", null, [item.eventType || "(none)"]),
      el("td", null, [item.eventId != null ? String(item.eventId) : "none"]),
      el("td", { className: "text-mono" }, [item.runId || "none"]),
      el("td", null, [item.ts ? formatAbsoluteTimestamp(item.ts) : "unavailable"]),
    );
  }, el("td", { colspan: "7" }, ["No evidence observed yet."]), "tr");
}

export async function render(root, params, ctx) {
  clear(root);
  const query = parseEvidenceQuery(new URLSearchParams(window.location.search));
  const repoId = params && params.repoId;
  root.appendChild(el("h1", { className: "text-display" }, ["Evidence"]));
  root.appendChild(el("p", { className: "text-muted" },
    ["Metadata only -- no raw record bytes or payload content is ever shown here."]));

  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Evidence"]),
    el("thead", null, [
      el("tr", null, [
        el("th", { scope: "col" }, ["Evidence ID"]),
        el("th", { scope: "col" }, ["Repository"]),
        el("th", { scope: "col" }, ["Integrity"]),
        el("th", { scope: "col" }, ["Event type"]),
        el("th", { scope: "col" }, ["Event ID"]),
        el("th", { scope: "col" }, ["Run"]),
        el("th", { scope: "col" }, ["Observed"]),
      ]),
    ]),
    el("tbody"),
  ]);
  wrapper.appendChild(table);
  root.appendChild(wrapper);

  const pagination = el("div", { className: "pagination" });
  root.appendChild(pagination);

  const tbody = table.querySelector("tbody");
  await loadEvidence(pagination, tbody, query, repoId, ctx);
}

async function loadEvidence(pagination, tbody, query, repoId, ctx) {
  try {
    const coordinator = ctx && ctx.coordinator;
    const url = buildApiUrl(query, repoId);
    const data = coordinator ? await coordinator.fetch("evidence:list", url) : await apiFetch(url);
    if (data === undefined) return;
    renderRows(tbody, data.items);

    clear(pagination);
    pagination.appendChild(el("p", { className: "pagination-status" }, [`${data.total} total`]));
    const controls = el("div", { className: "pagination-controls" });
    if (data.previous != null) {
      controls.appendChild(el("a", { className: "btn btn-secondary",
        href: _pageUrl(repoId, { afterEvidenceId: data.previous, direction: "asc" }) }, ["Previous"]));
    }
    if (data.hasMore && data.next != null) {
      controls.appendChild(el("a", { className: "btn btn-secondary",
        href: _pageUrl(repoId, { beforeEvidenceId: data.next, direction: "desc" }) }, ["Next"]));
    }
    pagination.appendChild(controls);
  } catch (err) {
    clear(tbody);
    tbody.appendChild(el("tr", null, [
      el("td", { colspan: "7", role: "alert" }, [`Could not load evidence: ${err.message}`]),
    ]));
  }
}

/** SSE-invalidation path (docs/27 SS9.3): re-fetches and syncList-updates
    the table body in place, reusing the mounted shell. Pagination
    controls are still rebuilt (never a keyed list, and the same keyset
    cursor params from the URL are reused, so Prev/Next targets stay
    correct) -- a smaller, less common focus target than a table row. */
export async function refresh(root, params, ctx) {
  const tbody = root.querySelector("tbody");
  const pagination = root.querySelector(".pagination");
  if (!tbody || !pagination) { await render(root, params, ctx); return; }
  const query = parseEvidenceQuery(new URLSearchParams(window.location.search));
  const repoId = params && params.repoId;
  await loadEvidence(pagination, tbody, query, repoId, ctx);
}

function _pageUrl(repoId, query) {
  const params = new URLSearchParams();
  if (query.beforeEvidenceId != null) params.set("beforeEvidenceId", String(query.beforeEvidenceId));
  if (query.afterEvidenceId != null) params.set("afterEvidenceId", String(query.afterEvidenceId));
  if (query.direction) params.set("direction", query.direction);
  const base = repoId ? `/repositories/${repoId}/evidence` : "/evidence";
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export async function renderDetail(root, params) {
  clear(root);
  const { repoId, evidenceId } = params;
  let evidence;
  try {
    evidence = await apiFetch(`/api/repositories/${repoId}/evidence/${encodeURIComponent(evidenceId)}`);
  } catch (err) {
    const notFound = err instanceof ApiError && err.status === 404;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" },
        [notFound ? "Evidence not found." : "Could not load this evidence record."]),
    ]));
    return;
  }

  const tone = _INTEGRITY_TONE[evidence.integrity] || "muted";
  root.appendChild(el("h1", { className: "text-display" }, [`Evidence ${evidence.evidenceId}`]));
  root.appendChild(el("p", null, [el("span", { className: `chip chip--${tone}` }, [evidence.integrity])]));

  const dl = el("dl", { className: "identity-block" }, [
    el("dt", null, ["Cursor"]), el("dd", { className: "text-mono" }, [evidence.cursor]),
    el("dt", null, ["Event type"]), el("dd", null, [evidence.eventType || "(none)"]),
    el("dt", null, ["Event ID"]), el("dd", null, [evidence.eventId != null ? String(evidence.eventId) : "none"]),
    el("dt", null, ["Schema version"]),
    el("dd", null, [evidence.schemaVersion != null ? String(evidence.schemaVersion) : "unavailable"]),
    el("dt", null, ["Issue"]),
    el("dd", null, [evidence.issueId
      ? el("a", { href: `/repositories/${repoId}/issues/${evidence.issueId}` }, [evidence.issueId])
      : "none"]),
    el("dt", null, ["Execution"]),
    el("dd", null, [evidence.executionId
      ? el("a", { href: `/repositories/${repoId}/executions/${evidence.executionId}` }, [evidence.executionId])
      : "none"]),
    el("dt", null, ["Run"]),
    el("dd", null, [evidence.runId
      ? el("a", { href: `/repositories/${repoId}/runs/${evidence.runId}` }, [evidence.runId])
      : "none"]),
    el("dt", null, ["Observed timestamp"]),
    el("dd", null, [evidence.ts
      ? timeElement(evidence.ts, formatAbsoluteTimestamp(evidence.ts), formatRelativeTime(evidence.ts, Date.now()))
      : "unavailable"]),
    el("dt", null, ["Record hash"]), el("dd", { className: "text-mono" }, [evidence.recordHash || "unavailable"]),
    el("dt", null, ["Length (bytes)"]),
    el("dd", null, [evidence.lengthBytes != null ? String(evidence.lengthBytes) : "unavailable"]),
  ]);
  root.appendChild(dl);

  if (evidence.integrity !== "OK") {
    root.appendChild(el("p", { className: "text-muted" }, [
      "Integrity/corruption details are tracked as repository health and attention facts, not shown here -- see ",
      el("a", { href: `/repositories/${repoId}` }, ["the repository overview"]), ".",
    ]));
  }
}
