"use strict";
// Configured issues + selection/run-control (ADR-30 / spec
// "Dashboard issue selection and run control", "User experience").
//
// Selection state lives on the mounted root (`root.__runControlSelection`,
// a Set<issueId>) rather than module scope, so it survives an SSE-triggered
// `refresh()` call without leaking across a real navigation to a different
// repository (a fresh `render()` always resets it) -- refresh() never
// selects a newly-appeared row on its own (spec: "preserve explicit
// selection ... without selecting newly appearing rows").
import { ApiError, apiFetch } from "../api.js";
import { openDialog } from "../components/dialog.js";
import { clear, el, syncList } from "../dom.js";
import { runDisplayOutcome } from "../format.js";

const _TERMINAL_STATES = new Set(["DONE", "NEEDS_HUMAN", "NEEDS_DECOMPOSITION"]);
const _STATE_TONE = {
  DONE: "ok", ACTIVE: "muted", PENDING: "muted",
  NEEDS_HUMAN: "danger", NEEDS_DECOMPOSITION: "warn",
  NOT_INGESTED: "muted", UNAVAILABLE: "danger",
};

function newIdempotencyKey() {
  return (crypto && crypto.randomUUID) ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorSummaryNode(root) {
  return root.querySelector("#run-control-errors");
}

function showErrors(root, lines) {
  const summary = errorSummaryNode(root);
  clear(summary);
  summary.appendChild(el("p", { className: "state-panel-title" }, ["This request cannot proceed:"]));
  const list = el("ul");
  for (const line of lines) list.appendChild(el("li", null, [line]));
  summary.appendChild(list);
  summary.hidden = false;
  summary.focus();
}

function clearErrors(root) {
  const summary = errorSummaryNode(root);
  if (summary) { summary.hidden = true; clear(summary); }
}

export function planRefusalLines(plan) {
  const lines = [];
  if (plan.emptySelection) lines.push("No issues are selected.");
  for (const id of plan.unknownIds || []) lines.push(`Unknown issue id: ${id}`);
  for (const id of plan.duplicateIds || []) lines.push(`Duplicate issue id: ${id}`);
  for (const t of plan.terminalSelected || []) lines.push(`${t.issueId} is already terminal (${t.state}).`);
  for (const b of plan.blockers || []) {
    lines.push(`${b.issueId} depends on ${b.missingDependencyId} (${b.dependencyState}), which is not selected or done.`);
  }
  if ((plan.cycleMembers || []).length) lines.push(`Dependency cycle: ${plan.cycleMembers.join(", ")}`);
  for (const id of plan.omittedActiveIds || []) {
    lines.push(`${id} is currently active and must be included in any new selection.`);
  }
  return lines;
}

function apiErrorLines(err) {
  if (err instanceof ApiError && err.status === 422 && err.details) {
    const lines = planRefusalLines(err.details);
    if (lines.length) return lines;
  }
  return [err.message || "Request failed."];
}

async function apiFetchWithDetails(path, options) {
  const resp = await fetch(path, options);
  let body = null;
  try { body = await resp.json(); } catch (e) { body = null; }
  if (!resp.ok) {
    const message = (body && body.error && body.error.message) || `request failed (${resp.status})`;
    const err = new ApiError(message, { code: body && body.error && body.error.code, status: resp.status });
    err.details = body && body.error && body.error.details;
    throw err;
  }
  return body;
}

function issueRow(issue, selection, onToggle) {
  const row = el("tr");
  const isTerminal = _TERMINAL_STATES.has(issue.state);
  const checkboxId = `run-control-select-${issue.issueId}`;
  const checkbox = el("input", {
    type: "checkbox", id: checkboxId,
    checked: selection.has(issue.issueId),
    disabled: isTerminal,
    "aria-label": `Select ${issue.issueId}`,
  });
  checkbox.addEventListener("change", () => onToggle(issue.issueId, checkbox.checked));
  const tone = _STATE_TONE[issue.state] || "muted";
  row.append(
    el("td", null, [checkbox]),
    el("th", { scope: "row" }, [issue.issueId]),
    el("td", null, [issue.title || ""]),
    el("td", null, [(issue.dependsOn || []).join(", ") || "—"]),
    el("td", null, [el("span", { className: `chip chip--${tone}` }, [issue.state])]),
  );
  return row;
}

function renderInfo(root, data) {
  const info = root.querySelector(".run-control-info");
  clear(info);
  info.append(
    el("dl", { className: "detail-meta" }, [
      el("dt", null, ["Config path"]), el("dd", null, [data.configPath || "—"]),
      el("dt", null, ["Issue file"]), el("dd", null, [data.issuesFilePath]),
      el("dt", null, ["Revision"]), el("dd", null, [data.issuesFileRevision.slice(0, 12) + "…"]),
    ]),
  );
  if (data.parserWarning) {
    info.appendChild(el("p", { className: "state-panel state-panel--warning", role: "status" }, [
      "One or more lines look like a bulleted “Depends-On:”. The parser only recognizes an ",
      "un-bulleted Depends-On: line; a bulleted one is treated as plain text and creates no dependency.",
    ]));
  }
  if ((data.activeIssuesOutsideFile || []).length) {
    info.appendChild(el("p", { className: "state-panel state-panel--warning", role: "status" }, [
      `Active issue(s) no longer in the configured file: ${data.activeIssuesOutsideFile.join(", ")}. `,
      "A new selection must include them or it will be refused.",
    ]));
  }
}

function updateActionState(root, data, selection) {
  const runSelectedBtn = root.querySelector("#run-control-run-selected");
  const runAllBtn = root.querySelector("#run-control-run-all");
  const controlsDisabled = data.readModelStatus !== "READY";
  runSelectedBtn.disabled = controlsDisabled || selection.size === 0;
  runAllBtn.disabled = controlsDisabled;
  const selectAll = root.querySelector("#run-control-select-all");
  if (selectAll) selectAll.disabled = controlsDisabled;
}

function confirmAndSubmit(root, repoId, ctx, { mode, issueIds, digest, plan, budget, projectPath }) {
  const orderedIds = plan.orderedIds || [];
  const excludedLines = (plan.excluded || []).map((e) => `${e.issueId} (${e.state})`);
  const body = [
    el("dl", { className: "detail-meta" }, [
      el("dt", null, ["Repository"]), el("dd", null, [projectPath || String(repoId)]),
      el("dt", null, ["Mode"]), el("dd", null, [mode === "ALL" ? "Run all" : "Run selected"]),
      el("dt", null, ["Issues to run"]), el("dd", null, [`${orderedIds.length}: ${orderedIds.join(", ") || "none"}`]),
      el("dt", null, ["Terminal exclusions"]),
      el("dd", null, [excludedLines.length ? excludedLines.join(", ") : "none"]),
      el("dt", null, ["Run-level budget"]),
      el("dd", null, [
        budget
          ? `max ${budget.maxExecutionsPerRun} executions, `
            + `max ${budget.maxAttemptsPerIssue} attempts/issue, `
            + `hard stop $${budget.hardStopProxyCostPerRunUsd}`
          : "unavailable",
      ]),
    ]),
  ];

  const { close } = openDialog({
    titleText: "Confirm run",
    bodyNodes: body,
    actions: [
      { label: "Cancel", className: "btn-ghost" },
      {
        label: "Start run", className: "btn btn-primary", autofocus: true,
        onClick: async () => {
          close();
          try {
            await apiFetchWithDetails(`/api/repositories/${repoId}/run-commands`, {
              method: "POST",
              headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
              body: JSON.stringify(
                mode === "ALL"
                  ? { mode: "ALL", expectedIssuesDigest: digest }
                  : { mode: "SELECTED", issueIds, expectedIssuesDigest: digest },
              ),
            });
            clearErrors(root);
            await loadAndRender(root, repoId, ctx);
          } catch (err) {
            showErrors(root, apiErrorLines(err));
          }
        },
      },
    ],
  });
}

async function submitPlan(root, repoId, ctx, mode) {
  const data = root.__runControlData;
  if (!data) return;
  clearStatus(root);
  const selection = root.__runControlSelection;
  const issueIds = mode === "SELECTED" ? Array.from(selection) : undefined;
  let plan;
  try {
    plan = await apiFetchWithDetails(`/api/repositories/${repoId}/run-plans`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        mode === "ALL"
          ? { mode: "ALL", expectedIssuesDigest: data.issuesFileRevision }
          : { mode: "SELECTED", issueIds, expectedIssuesDigest: data.issuesFileRevision },
      ),
    });
  } catch (err) {
    showErrors(root, apiErrorLines(err));
    return;
  }
  if (!plan.ok) {
    showErrors(root, planRefusalLines(plan));
    return;
  }
  clearErrors(root);
  if (plan.orderedIds.length === 0) {
    // ADR-30 review finding 9: a valid, zero-non-terminal-issue plan is a
    // clean no-op -- no confirmation dialog, no queue row, no process, and
    // no runtime workflow lifecycle event of any kind. Say so explicitly
    // rather than silently returning to an unchanged queue view.
    showStatus(root, noRunSummaryText(plan));
    return;
  }
  let projectPath;
  try {
    const repo = await apiFetch(`/api/repositories/${repoId}`);
    projectPath = repo.projectPath;
  } catch (e) { projectPath = undefined; }
  confirmAndSubmit(root, repoId, ctx, {
    mode, issueIds, digest: data.issuesFileRevision, plan, budget: data.budget, projectPath,
  });
}

export function noRunSummaryText(plan) {
  const total = plan.totalTerminalCount || 0;
  if (total === 0) return "Nothing to run; no issues are configured.";
  return `Nothing to run; ${total} issue${total === 1 ? " is" : "s are"} already terminal.`;
}

function showStatus(root, text) {
  const node = root.querySelector("#run-control-status");
  node.textContent = text;
  node.hidden = false;
}

function clearStatus(root) {
  const node = root.querySelector("#run-control-status");
  node.hidden = true;
  node.textContent = "";
}

export function queueStatusText(command) {
  if (command.status === "QUEUED" && command.queuePosition) {
    return `QUEUED (position ${command.queuePosition})`;
  }
  if (command.status === "COMPLETED") {
    // ADR-30 review blocker 1: COMPLETED here is exclusively a
    // process-exit-0 fact -- runtime.main documents that both the
    // runtime's own COMPLETED and INTERRUPTED outcomes can leave that
    // same exit code, so it must never be presented as batch success on
    // its own. Reuses format.js's own canonical runDisplayOutcome (the
    // same helper the event-derived /runs endpoint already uses) rather
    // than a second, hardcoded copy of its wording -- an unresolved run
    // is therefore never labelled "Running" here either.
    return `process exited — runtime: ${runDisplayOutcome(command.runtimeOutcome)}`;
  }
  return command.status;
}

export function queueModeSummaryText(command) {
  return `${command.mode}${command.issueIds ? ": " + command.issueIds.join(", ") : ""}`;
}

function renderQueue(root, commands) {
  const section = root.querySelector(".run-control-queue");
  clear(section);
  section.appendChild(el("h2", { className: "text-headline" }, ["Queue"]));
  const list = el("ul", { className: "entity-list", "aria-label": "Run commands" });
  syncList(list, commands, (c) => c.id, (node, c) => {
    clear(node);
    node.append(
      el("span", { className: "chip chip--muted" }, [queueStatusText(c)]),
      ` ${queueModeSummaryText(c)}`,
    );
    if (c.refusalReason) node.appendChild(el("p", { className: "text-muted" }, [c.refusalReason]));
  }, "No run commands yet.");
  section.appendChild(list);
}

async function loadAndRender(root, repoId, ctx) {
  const table = root.querySelector(".run-control-table tbody");
  let data;
  try {
    data = await apiFetch(`/api/repositories/${repoId}/configured-issues`);
  } catch (err) {
    clear(table);
    root.querySelector(".run-control-actions").hidden = true;
    table.closest("table").hidden = true;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" }, [err.message || "Could not load configured issues."]),
    ]));
    return;
  }
  root.__runControlData = data;
  root.querySelector(".run-control-actions").hidden = false;
  table.closest("table").hidden = false;
  renderInfo(root, data);

  const selection = root.__runControlSelection;
  // Never keep a now-terminal or now-vanished id selected.
  const validIds = new Set(data.issues.filter((i) => !_TERMINAL_STATES.has(i.state)).map((i) => i.issueId));
  for (const id of Array.from(selection)) if (!validIds.has(id)) selection.delete(id);

  syncList(table, data.issues, (i) => i.issueId, (node, issue) => {
    const fresh = issueRow(issue, selection, (id, checked) => {
      if (checked) selection.add(id); else selection.delete(id);
      updateActionState(root, data, selection);
    });
    while (node.firstChild) node.removeChild(node.firstChild);
    while (fresh.firstChild) node.appendChild(fresh.firstChild);
  }, el("td", { colspan: "5" }, ["No configured issues."]), "tr");

  updateActionState(root, data, selection);

  try {
    const queue = await apiFetch(`/api/repositories/${repoId}/run-commands`);
    renderQueue(root, queue.commands);
  } catch (e) { /* queue is supplementary -- a failure here doesn't block the page */ }
}

export async function render(root, params, ctx) {
  clear(root);
  const repoId = params.repoId;
  root.__runControlSelection = new Set();

  root.appendChild(el("h1", { className: "text-display" }, ["Run issues"]));
  root.appendChild(el("div", { className: "run-control-info" }));
  root.appendChild(el("div", {
    id: "run-control-errors", className: "state-panel state-panel--error",
    role: "alert", tabindex: "-1", hidden: true,
  }));
  root.appendChild(el("div", {
    id: "run-control-status", className: "state-panel state-panel--success",
    role: "status", hidden: true,
  }));

  const selectAll = el("input", { type: "checkbox", id: "run-control-select-all" });
  selectAll.addEventListener("change", () => {
    const data = root.__runControlData;
    if (!data) return;
    const selection = root.__runControlSelection;
    selection.clear();
    if (selectAll.checked) {
      for (const issue of data.issues) if (!_TERMINAL_STATES.has(issue.state)) selection.add(issue.issueId);
    }
    loadAndRender(root, repoId, ctx);
  });

  const runSelectedBtn = el("button", { type: "button", id: "run-control-run-selected", className: "btn btn-primary" },
    ["Run selected"]);
  runSelectedBtn.addEventListener("click", () => submitPlan(root, repoId, ctx, "SELECTED"));
  const runAllBtn = el("button", { type: "button", id: "run-control-run-all", className: "btn btn-secondary" },
    ["Run all"]);
  runAllBtn.addEventListener("click", () => submitPlan(root, repoId, ctx, "ALL"));

  root.appendChild(el("div", { className: "run-control-actions", hidden: true }, [
    el("label", { for: "run-control-select-all" }, [selectAll, " Select all"]),
    runSelectedBtn, runAllBtn,
  ]));

  const table = el("table", { className: "data-table run-control-table", hidden: true }, [
    el("caption", { className: "visually-hidden" }, ["Configured issues"]),
    el("thead", null, [el("tr", null, [
      el("th", { scope: "col" }, ["Select"]),
      el("th", { scope: "col" }, ["Issue"]),
      el("th", { scope: "col" }, ["Title"]),
      el("th", { scope: "col" }, ["Depends on"]),
      el("th", { scope: "col" }, ["State"]),
    ])]),
    el("tbody"),
  ]);
  // .ledger-table-wrapper (overflow-x: auto) -- matches issues.js's pattern
  // exactly, so a wide table scrolls within itself on a narrow viewport
  // instead of forcing the whole page to scroll horizontally.
  root.appendChild(el("div", { className: "ledger-table-wrapper" }, [table]));

  root.appendChild(el("section", { className: "run-control-queue" }));

  await loadAndRender(root, repoId, ctx);
}

export async function refresh(root, params, ctx) {
  if (!root.__runControlSelection) { await render(root, params, ctx); return; }
  await loadAndRender(root, params.repoId, ctx);
}
