"use strict";

const state = {
  selectedRepoId: null,
  eventSource: null,
};

function apiFetch(path, options) {
  return fetch(path, options).then(async (resp) => {
    let body = null;
    try {
      body = await resp.json();
    } catch (e) {
      body = null;
    }
    if (!resp.ok) {
      const message = (body && body.error && body.error.message) || `request failed (${resp.status})`;
      const err = new Error(message);
      err.code = body && body.error && body.error.code;
      err.status = resp.status;
      throw err;
    }
    return body;
  });
}

function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function badge(text, kind) {
  const span = document.createElement("span");
  span.className = "badge" + (kind ? ` badge-${kind}` : "");
  span.textContent = text;
  return span;
}

// ── keyed incremental list sync ─────────────────────────────────────────
// Never rebuilds the list with innerHTML: matches existing <li data-key>
// elements to the new item set by key, updates them in place, removes
// stragglers, appends new ones, and reorders via insertBefore only when
// order actually changed -- so focus/scroll/selection on unaffected rows
// survives a refresh.
function syncList(listEl, items, keyFn, renderFn, emptyMessage) {
  const existing = new Map();
  for (const child of Array.from(listEl.children)) {
    const key = child.getAttribute("data-key");
    if (key !== null) existing.set(key, child);
  }
  listEl.querySelectorAll("[data-empty-placeholder]").forEach((el) => el.remove());

  if (items.length === 0) {
    for (const child of existing.values()) child.remove();
    const placeholder = document.createElement("li");
    placeholder.className = "empty-state";
    placeholder.setAttribute("data-empty-placeholder", "");
    placeholder.textContent = emptyMessage;
    listEl.appendChild(placeholder);
    return;
  }

  let previousEl = null;
  const seen = new Set();
  for (const item of items) {
    const key = String(keyFn(item));
    seen.add(key);
    let el = existing.get(key);
    if (!el) {
      el = document.createElement("li");
      el.setAttribute("data-key", key);
    }
    renderFn(el, item);
    if (previousEl === null) {
      if (listEl.firstChild !== el) listEl.insertBefore(el, listEl.firstChild);
    } else if (previousEl.nextSibling !== el) {
      listEl.insertBefore(el, previousEl.nextSibling);
    }
    previousEl = el;
  }
  for (const [key, el] of existing) {
    if (!seen.has(key)) el.remove();
  }
}

// ── repository list ──────────────────────────────────────────────────
function renderRepoRow(el, repo) {
  clear(el);
  el.setAttribute("data-selected", String(repo.id === state.selectedRepoId));

  const info = document.createElement("div");
  const title = document.createElement("div");
  title.className = "entity-title";
  title.textContent = repo.projectPath;
  const meta = document.createElement("div");
  meta.className = "entity-meta";
  meta.textContent = repo.logPath ? `log: ${repo.logPath}` : "log: not configured";
  info.appendChild(title);
  info.appendChild(meta);

  const actions = document.createElement("div");
  const selectBtn = document.createElement("button");
  selectBtn.type = "button";
  selectBtn.className = "select-repo";
  selectBtn.textContent = repo.id === state.selectedRepoId ? "Selected" : "View";
  selectBtn.addEventListener("click", () => selectRepo(repo.id));
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "delete-repo";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => deleteRepo(repo.id));
  actions.appendChild(selectBtn);
  actions.appendChild(deleteBtn);

  el.appendChild(info);
  el.appendChild(actions);
}

async function refreshRepoList() {
  const data = await apiFetch("/api/repositories");
  syncList(
    document.getElementById("repo-list"),
    data.repositories,
    (r) => r.id,
    renderRepoRow,
    "No repositories registered yet.",
  );
}

async function selectRepo(id) {
  state.selectedRepoId = id;
  document.getElementById("repo-detail").hidden = false;
  document.getElementById("detail-repo-id").textContent = `#${id}`;
  await refreshRepoList(); // updates the "Selected" label on rows
  await Promise.all([
    refreshHealth(id), refreshRuns(id), refreshIssues(id), refreshExecutions(id), refreshEvidence(id),
  ]);
}

async function deleteRepo(id) {
  await apiFetch(`/api/repositories/${id}`, { method: "DELETE" });
  if (state.selectedRepoId === id) {
    state.selectedRepoId = null;
    document.getElementById("repo-detail").hidden = true;
  }
  await refreshRepoList();
}

document.getElementById("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorEl = document.getElementById("register-error");
  errorEl.textContent = "";
  const projectPath = document.getElementById("project-path").value.trim();
  const logPath = document.getElementById("log-path").value.trim();
  try {
    await apiFetch("/api/repositories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectPath, logPath: logPath || null }),
    });
    event.target.reset();
    await refreshRepoList();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ── health panel ─────────────────────────────────────────────────────
function renderHealth(health) {
  const panel = document.getElementById("health-panel");
  clear(panel);

  const availability = health.availability;
  const availabilityKind = {
    AVAILABLE: "ok", EMPTY: "muted", NOT_INITIALIZED: "warn", OFFLINE: "danger",
  }[availability];
  panel.appendChild(badge(availability === null ? "not yet observed" : availability,
    availability === null ? "muted" : (availabilityKind || "muted")));

  if (health.reducedConfidence) {
    panel.appendChild(badge("reduced identity confidence", "warn"));
  }
  if (health.corruptCount > 0) {
    panel.appendChild(badge(`CORRUPT (${health.corruptCount})`, "danger"));
  }
  if (health.unknownEventTypeCount > 0) {
    panel.appendChild(badge(`${health.unknownEventTypeCount} unknown event type(s)`, "warn"));
  }
  if (health.lease.status === "expired") {
    panel.appendChild(badge("indexer lease expired", "danger"));
  } else if (health.lease.status === "unclaimed") {
    panel.appendChild(badge("indexer lease unclaimed", "muted"));
  }

  if (health.haltedOversized) {
    const banner = document.createElement("p");
    banner.className = "halt-banner";
    banner.setAttribute("role", "alert");
    banner.textContent =
      "Indexing halted: an oversized record was found and ADR-25 exposes no " +
      "safe cursor beyond it. Operator remediation is required before this " +
      "repository can make further progress.";
    panel.appendChild(banner);
  }
}

async function refreshHealth(repoId) {
  const health = await apiFetch(`/api/repositories/${repoId}/health`);
  renderHealth(health);
}

// ── issues / executions / evidence ──────────────────────────────────
function stateBadgeKind(value) {
  if (value === "DONE" || value === "ACCEPTED") return "ok";
  if (value === "NEEDS_HUMAN" || value === "REJECTED" || value === "CRASHED") return "danger";
  if (value === "NEEDS_DECOMPOSITION" || value === "Pending reconciliation") return "warn";
  return "muted";
}

function renderIssueRow(el, issue) {
  clear(el);
  const info = document.createElement("div");
  const title = document.createElement("div");
  title.className = "entity-title";
  title.textContent = issue.title || issue.issueId;
  const meta = document.createElement("div");
  meta.className = "entity-meta";
  meta.textContent = `issue ${issue.issueId}`;
  info.appendChild(title);
  info.appendChild(meta);

  const right = document.createElement("div");
  right.appendChild(badge(issue.state, stateBadgeKind(issue.state)));
  if (issue.inconsistent) right.appendChild(badge("inconsistent", "warn"));

  el.appendChild(info);
  el.appendChild(right);
}

// Never "Running"/"in progress" -- ADR-25 gives Dashboard no liveness
// signal, so an unresolved RunStarted (no matching RunFinished yet) must
// never be rendered as a claim about current process state.
const NO_CONTROLLED_FINISH_TEXT = "no controlled finish observed";

// Run metadata is ALWAYS rendered -- either the real provider/model/outcome
// or the exact "run metadata unavailable (legacy/ambiguous)" fallback text.
// Never left blank (docs/19 "Run lifecycle compatibility"). Availability
// comes entirely from the runMetadata.available flag the server already
// computed from RunStarted evidence -- this function never inspects runId's
// string shape itself.
function runMetadataText(runMetadata) {
  if (!runMetadata || !runMetadata.available) {
    return (runMetadata && runMetadata.message) || "run metadata unavailable (legacy/ambiguous)";
  }
  const provider = runMetadata.engineProvider || "unknown engine";
  const model = runMetadata.engineModel || "unknown model";
  const outcome = runMetadata.outcome || NO_CONTROLLED_FINISH_TEXT;
  return `${provider} / ${model} — ${outcome}`;
}

function outcomeBadgeKind(displayOutcome) {
  if (displayOutcome === "COMPLETED") return "ok";
  if (displayOutcome === NO_CONTROLLED_FINISH_TEXT) return "muted";
  return "danger"; // any other controlled outcome is a failure/halt/interrupt
}

function renderRunRow(el, run) {
  clear(el);
  const info = document.createElement("div");
  const title = document.createElement("div");
  title.className = "entity-title";
  title.textContent = run.runId; // textContent only -- never innerHTML
  const meta = document.createElement("div");
  meta.className = "entity-meta";
  const provider = run.engineProvider || "unknown engine";
  const model = run.engineModel || "unknown model";
  const reviewer = run.reviewerProvider || "unknown reviewer";
  meta.textContent = `${provider} / ${model} — reviewer: ${reviewer}`;
  const digestMeta = document.createElement("div");
  digestMeta.className = "entity-meta";
  digestMeta.textContent = run.configDigest ? `digest: ${run.configDigest}` : "digest: unavailable";
  info.appendChild(title);
  info.appendChild(meta);
  info.appendChild(digestMeta);

  const right = document.createElement("div");
  right.appendChild(badge(run.displayOutcome, outcomeBadgeKind(run.displayOutcome)));
  if (run.inconsistent) right.appendChild(badge("inconsistent", "warn"));

  el.appendChild(info);
  el.appendChild(right);
}

async function refreshRuns(repoId) {
  const data = await apiFetch(`/api/repositories/${repoId}/runs`);
  syncList(document.getElementById("runs-list"), data.items, (r) => r.runId,
    renderRunRow, "No runs observed yet.");
}

function renderExecutionRow(el, execution) {
  clear(el);
  const info = document.createElement("div");
  const title = document.createElement("div");
  title.className = "entity-title";
  title.textContent = execution.executionId;
  const meta = document.createElement("div");
  meta.className = "entity-meta";
  meta.textContent = execution.issueId ? `issue ${execution.issueId}` : "issue unknown";
  const runMeta = document.createElement("div");
  runMeta.className = "entity-meta entity-run-meta";
  runMeta.textContent = runMetadataText(execution.runMetadata);
  info.appendChild(title);
  info.appendChild(meta);
  info.appendChild(runMeta);

  const right = document.createElement("div");
  right.appendChild(badge(execution.state, stateBadgeKind(execution.state)));
  if (execution.inconsistent) right.appendChild(badge("inconsistent", "warn"));
  if (execution.runMetadata && execution.runMetadata.inconsistent) {
    right.appendChild(badge("run inconsistent", "warn"));
  }

  el.appendChild(info);
  el.appendChild(right);
}

function renderEvidenceRow(el, record) {
  clear(el);
  const info = document.createElement("div");
  info.textContent = `#${record.eventId ?? "—"} ${record.eventType ?? "(no type)"}`;
  const right = document.createElement("div");
  const kind = record.integrity === "OK" ? "ok"
    : record.integrity === "TORN" ? "warn"
      : record.integrity === "OVERSIZED" ? "danger" : "muted";
  right.appendChild(badge(record.integrity, kind));
  el.appendChild(info);
  el.appendChild(right);
}

async function refreshIssues(repoId) {
  const data = await apiFetch(`/api/repositories/${repoId}/issues`);
  syncList(document.getElementById("issues-list"), data.items, (i) => i.issueId,
    renderIssueRow, "No issues observed yet.");
}

async function refreshExecutions(repoId) {
  const data = await apiFetch(`/api/repositories/${repoId}/executions`);
  syncList(document.getElementById("executions-list"), data.items, (e) => e.executionId,
    renderExecutionRow, "No executions observed yet.");
}

async function refreshEvidence(repoId) {
  const data = await apiFetch(`/api/repositories/${repoId}/evidence`);
  syncList(document.getElementById("evidence-list"), data.items, (r) => r.cursor,
    renderEvidenceRow, "No evidence observed yet.");
}

// ── SSE live updates ─────────────────────────────────────────────────
function connectEvents() {
  const statusEl = document.getElementById("connection-status");
  const source = new EventSource("/api/events");
  state.eventSource = source;

  source.onopen = () => {
    statusEl.textContent = "Live";
  };
  source.onerror = () => {
    statusEl.textContent = "Reconnecting…";
  };

  source.addEventListener("resync", () => {
    statusEl.textContent = "Resyncing…";
    refreshRepoList();
    if (state.selectedRepoId !== null) {
      refreshHealth(state.selectedRepoId);
      refreshRuns(state.selectedRepoId);
      refreshIssues(state.selectedRepoId);
      refreshExecutions(state.selectedRepoId);
      refreshEvidence(state.selectedRepoId);
    }
    // The resync event carries no id, so the browser's own Last-Event-ID
    // stays at whatever it was -- reconnecting the SAME EventSource would
    // just repeat the same expired cursor forever. Close it and open a
    // fresh one (no Last-Event-ID) so the next connect starts clean.
    source.close();
    window.setTimeout(connectEvents, 100);
  });

  source.addEventListener("change", (event) => {
    let change;
    try {
      change = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (state.selectedRepoId !== null && change.repositoryId === state.selectedRepoId) {
      refreshHealth(state.selectedRepoId);
      refreshRuns(state.selectedRepoId);
      refreshIssues(state.selectedRepoId);
      refreshExecutions(state.selectedRepoId);
      refreshEvidence(state.selectedRepoId);
    }
    refreshRepoList();
  });
}

// ── bootstrap ────────────────────────────────────────────────────────
refreshRepoList().catch((err) => {
  document.getElementById("register-error").textContent = err.message;
});
connectEvents();
