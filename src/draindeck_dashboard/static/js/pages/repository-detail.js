"use strict";
// Repository Overview (docs/27 SS6.3): identity block, health & attention
// panel, aggregates. Unregister remains reachable but visually separated,
// and requires an explicit confirmation before it deletes only
// Dashboard-owned rows -- never the target repository/log/artifacts.
import { ApiError, apiFetch } from "../api.js";
import { clear, el, statusChip } from "../dom.js";
import {
  availabilityLabel, averageCostText, coverageText, formatAbsoluteTimestamp, proxyCostText,
} from "../format.js";

const _AVAILABILITY_TONE = { AVAILABLE: "ok", EMPTY: "muted", NOT_INITIALIZED: "warn", OFFLINE: "danger" };
const _SEVERITY_TONE = { critical: "danger", warning: "warn", information: "muted" };

export const UNREGISTER_CONFIRM_TEXT =
  "This removes only Dashboard-owned registration, indexed evidence, projections, and attention " +
  "rows for this repository. It never deletes or modifies the repository, event log, transcripts, " +
  "diffs, or artifacts on disk.";

function renderIdentity(root, registration) {
  const dl = el("dl", { className: "identity-block" });
  const pairs = [
    ["Project path", registration.projectPath],
    ["Log path", registration.logPath || "not configured"],
    ["Registered", formatAbsoluteTimestamp(registration.createdAt) || registration.createdAt],
  ];
  for (const [label, value] of pairs) {
    dl.appendChild(el("dt", { className: "text-label" }, [label]));
    dl.appendChild(el("dd", null, [value]));
  }
  root.appendChild(dl);
}

function renderHealthPanel(root, health) {
  clear(root);
  const tone = _AVAILABILITY_TONE[health.availability] || "muted";
  root.appendChild(statusChip(availabilityLabel(health.availability), tone));
  if (health.reducedConfidence) root.appendChild(statusChip("Reduced identity confidence", "warn"));
  if (health.corruptCount > 0) root.appendChild(statusChip(`${health.corruptCount} corrupt`, "danger"));
  if (health.unknownEventTypeCount > 0) {
    root.appendChild(statusChip(`${health.unknownEventTypeCount} unknown event type(s)`, "warn"));
  }
  if (health.haltedOversized) {
    root.appendChild(el("p", { role: "alert", className: "state-panel state-panel--error" },
      ["Indexing halted at an oversized record; operator remediation required."]));
  }
  const leaseTone = health.lease.status === "held" ? "ok"
    : health.lease.status === "expired" ? "danger" : "muted";
  root.appendChild(statusChip(`Indexer lease: ${health.lease.status}`, leaseTone));
}

function renderAttentionPanel(root, overview) {
  clear(root);
  if (overview.attention.current === 0) {
    root.appendChild(el("p", { className: "text-muted" }, ["No current attention conditions."]));
    return;
  }
  const list = el("ul", { className: "entity-list", "aria-label": "Repository attention" });
  for (const item of overview.attention.items) {
    const tone = _SEVERITY_TONE[item.severity] || "muted";
    list.appendChild(el("li", null, [
      statusChip(item.severity, tone),
      el("a", { href: item.targetUrl }, [item.message]),
    ]));
  }
  root.appendChild(list);
}

function renderUnregisterDialog(root, repoId, repoDisplayName, triggerEl) {
  const backdrop = el("div", { className: "dialog-backdrop", role: "presentation" });
  const dialog = el("div", { className: "dialog", role: "alertdialog", "aria-modal": "true",
                            "aria-labelledby": "unregister-dialog-heading" });
  dialog.appendChild(el("h2", { id: "unregister-dialog-heading", className: "text-headline" },
    [`Unregister ${repoDisplayName}?`]));
  dialog.appendChild(el("p", null, [UNREGISTER_CONFIRM_TEXT]));
  const alertEl = el("p", { role: "alert", className: "field-error-text" });
  const actions = el("div", { className: "dialog-actions" });
  const cancelBtn = el("button", { type: "button", className: "btn btn-secondary" }, ["Cancel"]);
  const confirmBtn = el("button", { type: "button", className: "btn btn-destructive" }, ["Unregister"]);
  actions.append(cancelBtn, confirmBtn);
  dialog.append(actions, alertEl);
  backdrop.appendChild(dialog);
  document.body.appendChild(backdrop);
  confirmBtn.focus();

  // Focus must return to whatever opened the dialog on every close path
  // (cancel, Escape, or a successful delete) -- never left on a removed
  // node or silently dropped to <body>.
  function close({ returnFocus = true } = {}) {
    backdrop.remove();
    document.removeEventListener("keydown", onKeydown);
    if (returnFocus && triggerEl && triggerEl.isConnected) triggerEl.focus();
  }
  // A minimal manual focus trap: this dialog only ever has these two
  // focusable elements, so cycling between them directly is simpler and
  // more robust than computing the full focusable-descendant set. Without
  // this, Tab/Shift+Tab from the last/first button escapes into the
  // underlying page while the modal backdrop is still shown.
  function onKeydown(event) {
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key !== "Tab") return;
    event.preventDefault();
    const next = event.shiftKey
      ? (document.activeElement === cancelBtn ? confirmBtn : cancelBtn)
      : (document.activeElement === confirmBtn ? cancelBtn : confirmBtn);
    next.focus();
  }
  document.addEventListener("keydown", onKeydown);
  cancelBtn.addEventListener("click", () => close());

  confirmBtn.addEventListener("click", async () => {
    try {
      await apiFetch(`/api/repositories/${repoId}`, { method: "DELETE" });
      // The repository is gone and we're navigating away -- returning
      // focus to a now-meaningless trigger button would be worse than
      // leaving it at the removed dialog's position (browsers fall back
      // to <body>, and the new route's own focus-on-navigate takes over).
      close({ returnFocus: false });
      window.history.pushState({}, "", "/repositories");
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (err) {
      alertEl.textContent = err instanceof ApiError ? err.message : String(err);
    }
  });
}

export async function render(root, params, ctx) {
  clear(root);
  const repoId = params.repoId;
  let registration, health, overview;
  try {
    [registration, health, overview] = await Promise.all([
      apiFetch(`/api/repositories/${repoId}`),
      apiFetch(`/api/repositories/${repoId}/health`),
      apiFetch(`/api/repositories/${repoId}/overview`),
    ]);
  } catch (err) {
    const notFound = err instanceof ApiError && err.status === 404;
    root.appendChild(el("div", { className: "state-panel state-panel--error", role: "alert" }, [
      el("p", { className: "state-panel-title" },
        [notFound ? "Repository not found." : "Could not load this repository."]),
    ]));
    return;
  }

  root.appendChild(el("h1", { className: "text-display" }, [registration.projectPath]));

  const identitySection = el("section", { "aria-label": "Identity" });
  renderIdentity(identitySection, registration);
  root.appendChild(identitySection);

  const healthSection = el("section", { "aria-label": "Health" });
  renderHealthPanel(healthSection, health);
  root.appendChild(healthSection);

  const attentionSection = el("section", { "aria-label": "Attention" }, [
    el("h2", { className: "text-headline" }, ["Attention"]),
  ]);
  renderAttentionPanel(attentionSection, overview);
  root.appendChild(attentionSection);

  // Proxy cost (spec §5): repository total, completed-issue average, coverage.
  const costSection = el("section", { "aria-label": "Proxy cost" }, [
    el("h2", { className: "text-headline" }, ["Proxy cost"]),
    el("dl", { className: "identity-block" }, [
      el("dt", null, ["Total observed proxy cost"]),
      el("dd", null, [proxyCostText(overview.proxyCost)]),
      el("dt", null, ["Coverage"]),
      el("dd", null, [coverageText(overview.proxyCost)]),
      el("dt", null, ["Observed average per completed issue"]),
      el("dd", null, [averageCostText(overview.averageProxyCostPerCompletedIssue)]),
    ]),
  ]);
  root.appendChild(costSection);

  const navSection = el("section", { className: "detail-nav" }, [
    el("a", { href: `/repositories/${repoId}/runs`, className: "btn-ghost" }, ["Runs"]),
    el("a", { href: `/repositories/${repoId}/issues`, className: "btn-ghost" }, ["Issues"]),
    el("a", { href: `/repositories/${repoId}/executions`, className: "btn-ghost" }, ["Executions"]),
    el("a", { href: `/repositories/${repoId}/evidence`, className: "btn-ghost" }, ["Evidence"]),
  ]);
  root.appendChild(navSection);

  const unregisterSection = el("section", { className: "unregister-section" });
  const unregisterBtn = el("button", { type: "button", className: "btn btn-destructive" },
    ["Unregister repository"]);
  unregisterBtn.addEventListener("click", () => {
    renderUnregisterDialog(root, repoId, registration.projectPath, unregisterBtn);
  });
  unregisterSection.appendChild(unregisterBtn);
  root.appendChild(unregisterSection);
}
