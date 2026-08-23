"use strict";
// Attention Center (docs/27 SS6.4): cross-repository current/resolved
// detected conditions, closed severity ordering (critical -> warning ->
// informational, then oldest first), never dismissible.
import { apiFetch } from "../api.js";
import { clear, el, statusChip } from "../dom.js";
import { formatAbsoluteTimestamp } from "../format.js";

const _SEVERITY_TONE = { critical: "danger", warning: "warn", information: "muted" };
export const STATUS_FILTERS = [
  { value: "current", label: "Current" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

/** Pure: parses the Attention Center's shareable filter state from a
    URLSearchParams-like object. */
export function parseAttentionQuery(searchParams) {
  const status = searchParams.get("status");
  return {
    status: STATUS_FILTERS.some((f) => f.value === status) ? status : "current",
    severity: searchParams.get("severity") || "",
  };
}

function buildApiUrl(query) {
  const params = new URLSearchParams();
  params.set("limit", "200");
  params.set("status", query.status);
  if (query.severity) params.set("severity", query.severity);
  return `/api/attention?${params.toString()}`;
}

function renderRow(item) {
  const tone = _SEVERITY_TONE[item.severity] || "muted";
  const row = el("tr");
  row.append(
    el("td", null, [statusChip(item.severity, tone)]),
    el("td", null, [item.kind.replace(/_/g, " ")]),
    el("td", null, [item.repository
      ? el("a", { href: `/repositories/${item.repository.id}` }, [`Repository ${item.repository.id}`])
      : "All repositories"]),
    el("td", null, [el("a", { href: item.targetUrl }, [item.message])]),
    el("td", null, [formatAbsoluteTimestamp(item.firstDetectedAt) || item.firstDetectedAt]),
    el("td", null, [formatAbsoluteTimestamp(item.lastDetectedAt) || item.lastDetectedAt]),
    el("td", null, [item.resolvedAt ? "Resolved" : "Current"]),
  );
  return row;
}

export async function render(root, params, ctx) {
  clear(root);
  const query = parseAttentionQuery(new URLSearchParams(window.location.search));

  root.appendChild(el("h1", { className: "text-display" }, ["Attention"]));

  const filterBar = el("div", { className: "registry-filters", role: "group",
                              "aria-label": "Attention status filter" });
  for (const filter of STATUS_FILTERS) {
    const pressed = filter.value === query.status;
    const chip = el("button", { type: "button", className: "filter-chip",
                              "aria-pressed": String(pressed) }, [filter.label]);
    chip.addEventListener("click", () => {
      const url = filter.value === "current" ? "/attention" : `/attention?status=${filter.value}`;
      // Same-page filter -- keep focus on the equivalent new chip rather
      // than yanking it to the main landmark (docs/27 SS9.2). render()
      // rebuilds the filter bar synchronously before its first `await`,
      // so the new pressed chip already exists in `root` by the time
      // navigate() returns here -- the OLD chip node (which had focus)
      // was destroyed by that same rebuild, so simply not-stealing-focus
      // isn't enough; focus must be moved to its replacement explicitly.
      if (ctx && ctx.navigate) {
        ctx.navigate(url, { preserveFocus: true });
        const newChip = root.querySelector('.filter-chip[aria-pressed="true"]');
        if (newChip) newChip.focus();
      } else { window.history.pushState({}, "", url); window.dispatchEvent(new PopStateEvent("popstate")); }
    });
    filterBar.appendChild(chip);
  }
  root.appendChild(filterBar);

  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Attention conditions"]),
    el("thead", null, [
      el("tr", null, [
        el("th", { scope: "col" }, ["Severity"]),
        el("th", { scope: "col" }, ["Condition"]),
        el("th", { scope: "col" }, ["Scope"]),
        el("th", { scope: "col" }, ["Subject"]),
        el("th", { scope: "col" }, ["First detected"]),
        el("th", { scope: "col" }, ["Last detected"]),
        el("th", { scope: "col" }, ["Status"]),
      ]),
    ]),
    el("tbody"),
  ]);
  wrapper.appendChild(table);
  root.appendChild(wrapper);

  const tbody = table.querySelector("tbody");
  try {
    const coordinator = ctx && ctx.coordinator;
    const data = coordinator
      ? await coordinator.fetch("attention:list", buildApiUrl(query))
      : await apiFetch(buildApiUrl(query));
    if (data === undefined) return; // superseded
    if (data.items.length === 0) {
      tbody.appendChild(el("tr", null, [
        el("td", { colspan: "7" }, [
          query.status === "current" ? "No current attention conditions." : "No conditions found.",
        ]),
      ]));
    } else {
      for (const item of data.items) tbody.appendChild(renderRow(item));
    }
  } catch (err) {
    clear(tbody);
    tbody.appendChild(el("tr", null, [
      el("td", { colspan: "7", role: "alert" }, [`Could not load attention: ${err.message}`]),
    ]));
  }
}
