"use strict";
// Executions Explorer and Execution Detail (docs/27 SS6.7). groupBy is
// server-backed/pagination-correct, never a client-page join. Transcript
// and diff are rendered as text only -- never markup -- and no duration
// is ever shown (the contract establishes none).
import { ApiError, apiFetch, apiFetchText } from "../api.js";
import { clear, el, syncList } from "../dom.js";
import {
  coverageText, inconsistencyLabel, isPartialCost, proxyCostText, runMetadataText,
} from "../format.js";
import {
  isIndexPreparingError, preparingRow, projectionIncompleteBanner, removeReadinessBanner,
  renderPreparingPanel, staleBanner,
} from "../readiness.js";

const _STATE_TONE = {
  ACCEPTED: "ok", REJECTED: "danger", CRASHED: "danger", "Pending reconciliation": "warn",
  VALIDATING: "muted", REVIEWING: "muted",
};
const _CONTAINMENT_TONE = { PREPARED: "muted", ESTABLISHED: "ok", UNCONFIRMED: "danger", RELEASED: "ok" };

/** Pure: parses the explorer's groupBy state from a URLSearchParams-like
    object, defaulting safely to "execution" on any other value. */
export function parseGroupBy(searchParams) {
  const value = searchParams.get("groupBy");
  return value === "issue" ? "issue" : "execution";
}

function renderExecutionRows(tbody, items) {
  syncList(tbody, items, (execution) => `${execution.repository.id}:${execution.executionId}`,
    (row, execution) => {
      clear(row);
      const tone = _STATE_TONE[execution.state] || "muted";
      row.append(
        el("td", null, [execution.repository.displayName]),
        el("th", { scope: "row" }, [
          el("a", { href: `/repositories/${execution.repository.id}/executions/${execution.executionId}`,
                   className: "row-title" }, [execution.executionId]),
        ]),
        el("td", null, [execution.issueId
          ? el("a", { href: `/repositories/${execution.repository.id}/issues/${execution.issueId}` },
              [execution.issueId])
          : "none"]),
        el("td", null, [el("span", { className: `chip chip--${tone}` }, [execution.state])]),
        _execCostCell(execution.proxyCost),
        el("td", null, [inconsistencyLabel(execution.inconsistent)]),
      );
    }, el("td", { colspan: "6" }, ["No executions observed yet."]), "tr");
}

function _execCostCell(proxyCost) {
  const cell = el("td", null, [proxyCostText(proxyCost)]);
  if (isPartialCost(proxyCost)) {
    cell.appendChild(el("span", { className: "chip chip--warn", title: coverageText(proxyCost) },
      ["Partial"]));
  }
  return cell;
}

function renderIssueGroups(tbody, items) {
  syncList(tbody, items, (group) => `${group.repository.id}:${group.issue.issueId}`, (row, group) => {
    clear(row);
    const byStateText = Object.entries(group.byState).map(([k, v]) => `${k}: ${v}`).join(", ");
    row.append(
      el("td", null, [group.repository.displayName]),
      el("th", { scope: "row" }, [
        el("a", { href: `/repositories/${group.repository.id}/issues/${group.issue.issueId}`,
                 className: "row-title" }, [group.issue.title || group.issue.issueId]),
      ]),
      el("td", null, [`${group.totalExecutions} total (${byStateText})`]),
      el("td", null, [
        group.executionsTruncated
          ? el("a", { href: `/repositories/${group.repository.id}/executions?issueId=${group.issue.issueId}` },
              ["View all"])
          : `${group.newestExecutions.length} shown`,
      ]),
    );
  }, el("td", { colspan: "4" }, ["No executions observed yet."]), "tr");
}

export async function render(root, params, ctx) {
  clear(root);
  const groupBy = parseGroupBy(new URLSearchParams(window.location.search));
  root.appendChild(el("h1", { className: "text-display" }, ["Executions"]));

  const toggleBar = el("div", { className: "registry-filters", role: "group",
                              "aria-label": "Group executions" });
  for (const [value, label] of [["execution", "By execution"], ["issue", "By issue"]]) {
    const pressed = value === groupBy;
    const chip = el("button", { type: "button", className: "filter-chip",
                              "aria-pressed": String(pressed) }, [label]);
    chip.addEventListener("click", () => {
      const url = value === "execution" ? "/executions" : "/executions?groupBy=issue";
      // Same-page toggle -- keep focus on the equivalent new chip (the
      // old one is destroyed by render()'s synchronous rebuild), not the
      // main landmark.
      if (ctx && ctx.navigate) {
        ctx.navigate(url, { preserveFocus: true });
        const newChip = root.querySelector('.filter-chip[aria-pressed="true"]');
        if (newChip) newChip.focus();
      } else { window.history.pushState({}, "", url); window.dispatchEvent(new PopStateEvent("popstate")); }
    });
    toggleBar.appendChild(chip);
  }
  root.appendChild(toggleBar);

  const isIssueGroup = groupBy === "issue";
  const headerCells = isIssueGroup
    ? ["Repository", "Issue", "Executions", "Newest"]
    : ["Repository", "Execution", "Issue", "State", "Proxy cost", "Inconsistency"];
  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Executions"]),
    el("thead", null, [el("tr", null, headerCells.map((h) => el("th", { scope: "col" }, [h])))]),
    el("tbody"),
  ]);
  wrapper.appendChild(table);
  root.appendChild(wrapper);

  const repoId = params && params.repoId;
  const tbody = table.querySelector("tbody");
  await loadExecutions(root, wrapper, tbody, repoId, groupBy, isIssueGroup, headerCells.length, ctx);
}

async function loadExecutions(root, wrapper, tbody, repoId, groupBy, isIssueGroup, colspan, ctx) {
  const base = repoId ? `/api/executions?repositoryId=${repoId}` : "/api/executions?";
  const url = `${base}${repoId ? "&" : ""}groupBy=${groupBy}&limit=100`;
  try {
    const coordinator = ctx && ctx.coordinator;
    const data = coordinator ? await coordinator.fetch("executions:list", url) : await apiFetch(url);
    if (data === undefined) return;
    removeReadinessBanner(root);
    if (data.stale) root.insertBefore(staleBanner(), wrapper);
    else if (data.projectionState && !data.projectionState.complete) {
      root.insertBefore(projectionIncompleteBanner(), wrapper);
    }
    if (isIssueGroup) renderIssueGroups(tbody, data.items);
    else renderExecutionRows(tbody, data.items);
  } catch (err) {
    clear(tbody);
    if (isIndexPreparingError(err)) tbody.appendChild(preparingRow(colspan));
    else tbody.appendChild(el("tr", null, [
      el("td", { colspan: String(colspan), role: "alert" },
        [`Could not load executions: ${err.message}`]),
    ]));
  }
}

/** SSE-invalidation path (docs/27 SS9.3): re-fetches and syncList-updates
    only the table body/banner, reusing the mounted shell (including the
    groupBy toggle's current selection -- a mode CHANGE is always a real
    navigation via ctx.navigate, never something refresh() itself does). */
export async function refresh(root, params, ctx) {
  const wrapper = root.querySelector(".ledger-table-wrapper");
  const tbody = root.querySelector("tbody");
  if (!wrapper || !tbody) { await render(root, params, ctx); return; }
  const groupBy = parseGroupBy(new URLSearchParams(window.location.search));
  const isIssueGroup = groupBy === "issue";
  const colspan = tbody.closest("table").querySelectorAll("thead th").length;
  const repoId = params && params.repoId;
  await loadExecutions(root, wrapper, tbody, repoId, groupBy, isIssueGroup, colspan, ctx);
}

function renderContainments(root, containments) {
  clear(root);
  if (containments.length === 0) {
    root.appendChild(el("p", { className: "text-muted" }, ["No containment observed yet."]));
    return;
  }
  const list = el("ul", { className: "entity-list", "aria-label": "Containment generations" });
  for (const c of containments) {
    const tone = _CONTAINMENT_TONE[c.state] || "muted";
    list.appendChild(el("li", null, [
      el("span", { className: "text-mono" }, [`generation ${c.containmentGeneration}`]),
      el("span", { className: `chip chip--${tone}` }, [c.state]),
      c.workspaceKey ? el("span", { className: "text-muted" }, [`workspace: ${c.workspaceKey}`]) : null,
      c.inconsistent ? el("span", { className: "chip chip--warn" }, ["inconsistent"]) : null,
    ]));
  }
  root.appendChild(list);
}

async function renderTranscriptTab(panel, repoId, executionId) {
  clear(panel);
  panel.appendChild(el("p", { className: "skeleton" }, ["Loading transcript…"]));
  try {
    const text = await apiFetchText(`/api/repositories/${repoId}/executions/${executionId}/transcript`);
    clear(panel);
    panel.appendChild(el("pre", { className: "artifact-viewer text-mono" }, [text]));
  } catch (err) {
    clear(panel);
    const notFound = err instanceof ApiError && err.status === 404;
    const forbidden = err instanceof ApiError && err.status === 403;
    panel.appendChild(el("p", { role: "alert" }, [
      forbidden ? "Transcript is outside the permitted artifact root."
        : notFound ? "No transcript available for this execution."
        : `Could not load transcript: ${err.message}`,
    ]));
  }
}

async function renderDiffTab(panel, repoId, executionId) {
  clear(panel);
  panel.appendChild(el("p", { className: "skeleton" }, ["Loading diff…"]));
  try {
    const data = await apiFetch(`/api/repositories/${repoId}/executions/${executionId}/diff`);
    clear(panel);
    if (!data.diff) {
      panel.appendChild(el("p", { className: "text-muted" }, ["No changes (empty diff)."]));
    } else {
      panel.appendChild(el("pre", { className: "artifact-viewer text-mono" }, [data.diff]));
      if (data.truncated) {
        panel.appendChild(el("p", { role: "note", className: "text-muted" },
          [`Diff truncated at ${data.sizeBytes} bytes.`]));
      }
    }
  } catch (err) {
    clear(panel);
    panel.appendChild(el("p", { role: "alert" }, [`Could not load diff: ${err.message}`]));
  }
}

export async function renderDetail(root, params) {
  clear(root);
  const { repoId, executionId } = params;
  let execution;
  try {
    execution = await apiFetch(`/api/repositories/${repoId}/executions/${encodeURIComponent(executionId)}`);
  } catch (err) {
    if (isIndexPreparingError(err)) {
      renderPreparingPanel(root);
      return;
    }
    const notFound = err instanceof ApiError && err.status === 404;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" },
        [notFound ? "Execution not found." : "Could not load this execution."]),
    ]));
    return;
  }

  const tone = _STATE_TONE[execution.state] || "muted";
  root.appendChild(el("h1", { className: "text-display" }, [execution.executionId]));
  root.appendChild(el("p", null, [
    el("span", { className: `chip chip--${tone}` }, [execution.state]),
    ` ${inconsistencyLabel(execution.inconsistent)}`,
  ]));

  const metaDl = el("dl", { className: "identity-block" }, [
    el("dt", null, ["Issue"]),
    el("dd", null, [execution.issueId
      ? el("a", { href: `/repositories/${repoId}/issues/${execution.issueId}` }, [execution.issueId])
      : "none"]),
    el("dt", null, ["Run"]),
    el("dd", null, [execution.runId
      ? el("a", { href: `/repositories/${repoId}/runs/${execution.runId}` }, [execution.runId])
      : "none"]),
    el("dt", null, ["Run metadata"]),
    el("dd", null, [runMetadataText(execution.runMetadata)]),
    el("dt", null, ["Proxy cost"]),
    el("dd", null, [proxyCostText(execution.proxyCost)]),
    el("dt", null, ["Last event"]),
    el("dd", null, [execution.lastEventId != null ? String(execution.lastEventId) : "none"]),
  ]);
  root.appendChild(metaDl);

  root.appendChild(el("h2", { className: "text-headline" }, ["Containment"]));
  const containmentContainer = el("div");
  renderContainments(containmentContainer, execution.containments);
  root.appendChild(containmentContainer);

  root.appendChild(el("h2", { className: "text-headline" }, ["Artifacts"]));
  const tabList = el("div", { role: "tablist", "aria-label": "Artifact viewer", className: "tab-list" });
  const transcriptTab = el("button", { type: "button", role: "tab", "aria-selected": "true",
                                      tabindex: "0",
                                      id: "tab-transcript", "aria-controls": "panel-transcript" },
    ["Transcript"]);
  const diffTab = el("button", { type: "button", role: "tab", "aria-selected": "false",
                                tabindex: "-1",
                                id: "tab-diff", "aria-controls": "panel-diff" }, ["Diff"]);
  const tabs = [transcriptTab, diffTab];
  tabList.append(transcriptTab, diffTab);
  root.appendChild(tabList);

  const transcriptPanel = el("div", { role: "tabpanel", id: "panel-transcript",
                                     "aria-labelledby": "tab-transcript" });
  const diffPanel = el("div", { role: "tabpanel", id: "panel-diff", "aria-labelledby": "tab-diff",
                                hidden: true });
  root.append(transcriptPanel, diffPanel);

  function activate(tab) {
    const showTranscript = tab === "transcript";
    transcriptTab.setAttribute("aria-selected", String(showTranscript));
    diffTab.setAttribute("aria-selected", String(!showTranscript));
    transcriptTab.tabIndex = showTranscript ? 0 : -1;
    diffTab.tabIndex = showTranscript ? -1 : 0;
    transcriptPanel.hidden = !showTranscript;
    diffPanel.hidden = showTranscript;
  }
  transcriptTab.addEventListener("click", () => activate("transcript"));
  diffTab.addEventListener("click", () => activate("diff"));

  /** WAI-ARIA APG tablist pattern (automatic activation): Left/Right move
      focus AND select the adjacent tab, wrapping at the ends; Home/End
      jump to the first/last tab. Only the selected tab is in the Tab
      order (roving tabindex, set in `activate`) -- Left/Right/Home/End
      move focus WITHIN the tablist without another Tab press. */
  tabList.addEventListener("keydown", (event) => {
    const currentIndex = tabs.indexOf(document.activeElement);
    if (currentIndex === -1) return;
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = tabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = tabs[nextIndex];
    activate(nextTab === transcriptTab ? "transcript" : "diff");
    nextTab.focus();
  });

  await renderTranscriptTab(transcriptPanel, repoId, executionId);
  await renderDiffTab(diffPanel, repoId, executionId);
}
