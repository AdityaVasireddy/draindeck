"use strict";
// Shared "indexed views are still preparing / a snapshot exists but is
// stale/rebuilding" rendering (docs/27 SS3.2 decision 9), reused across
// every repository-scoped explorer/detail page so the exact wording and
// markup stay identical everywhere this state can occur.
import { ApiError } from "./api.js";
import { el, statusChip } from "./dom.js";

export const PREPARING_TEXT = "Preparing indexed views.";
export const PREPARING_DETAIL_TEXT =
  "This repository's indexed views are still being built. Data will appear once the initial index completes.";
export const STALE_TEXT =
  "This view reflects the last complete snapshot; it is being rebuilt and may be briefly out of date.";
export const PROJECTION_INCOMPLETE_TEXT =
  "One or more repositories are still preparing their indexed views; their data is not yet reflected below.";

export function isIndexPreparingError(err) {
  return err instanceof ApiError && err.code === "INDEX_PREPARING";
}

/** A full-width, non-table state panel for a detail page or any
    container that isn't a `<tbody>`. */
export function renderPreparingPanel(root) {
  root.appendChild(el("div", { className: "state-panel", role: "status" }, [
    el("p", { className: "state-panel-title" }, [PREPARING_TEXT]),
    el("p", { className: "text-muted" }, [PREPARING_DETAIL_TEXT]),
  ]));
}

/** A single `<tr>` for a `<tbody>`-based explorer table, matching the
    existing empty/error row shape (one cell spanning every column). */
export function preparingRow(colspan) {
  const row = el("tr");
  row.appendChild(el("td", { colspan: String(colspan), role: "status" }, [PREPARING_TEXT]));
  return row;
}

const _BANNER_MARKER = "data-readiness-banner";

/** A dismissible-free, always-visible banner for a page whose data is
    being served stale/rebuilding (docs/27 SS3.2 decision 9's "labelled
    stale/rebuilding" -- data stays on screen, just honestly labelled). */
export function staleBanner() {
  return el("p", { className: "state-panel state-panel--warning", role: "status", [_BANNER_MARKER]: "" },
    [STALE_TEXT]);
}

/** The cross-repository counterpart: never blocks (docs/27 SS3.2 decision
    9), just discloses that the aggregate below doesn't yet reflect every
    repository. */
export function projectionIncompleteBanner() {
  return el("p", { className: "state-panel state-panel--warning", role: "status", [_BANNER_MARKER]: "" },
    [PROJECTION_INCOMPLETE_TEXT]);
}

/** Removes any previously-inserted stale/projectionIncomplete banner --
    call before conditionally inserting a fresh one so a `refresh()` path
    (which reuses the DOM across repeated SSE invalidations, unlike
    `render()`'s clear(root)) never stacks up duplicate banners. */
export function removeReadinessBanner(root) {
  const existing = root.querySelector(`[${_BANNER_MARKER}]`);
  if (existing) existing.remove();
}

const _MISSING_PREREQUISITE_TEXT = {
  claude: { label: "Claude Code", action: "install Claude Code" },
  ollama: { label: "Ollama", action: "install Ollama" },
  "reviewer-model": { label: "the configured reviewer model", action: "pull the configured reviewer model" },
  "repository-not-registered": {
    label: "no repository registered", action: "register a repository to configure a run",
  },
  "repository-not-selected": {
    label: "no repository selected", action: "open a specific repository to see its run readiness",
  },
  "reviewer-model-not-configured": {
    label: "reviewer model not configured", action: "configure a reviewer model for this repository",
  },
  "config-unavailable": {
    label: "the repository's configuration file is unavailable",
    action: "check that .draindeck/config.local.yaml still exists and is readable",
  },
  "config-invalid": {
    label: "the repository's configuration file is invalid",
    action: "fix .draindeck/config.local.yaml, then reload",
  },
};

/** Renders the launcher's independent Dashboard-ready / Run-ready states
    (docs/32 L-10): the Dashboard can be usable while a run is not, and the
    UI must say so honestly rather than implying both are ready together.
    `missing` (from /api/launcher/readiness) names each absent
    prerequisite by id -- shown with its human label and a concrete next
    action, never a bare "not ready" with no explanation. */
export function renderLauncherReadiness({ dashboardReady, runReady, missing, model }) {
  const dashboardChip = statusChip(
    dashboardReady ? "Dashboard ready" : "Dashboard not ready",
    dashboardReady ? "success" : "warning",
  );
  const runChip = statusChip(
    runReady ? "Run ready" : "Run not ready",
    runReady ? "success" : "warning",
  );
  const children = [dashboardChip, runChip];
  if (!runReady && missing && missing.length > 0) {
    const items = missing.map((id) => {
      const known = _MISSING_PREREQUISITE_TEXT[id];
      const li = el("li", null, [known ? `${known.label} — ${known.action}.` : `${id} is missing.`]);
      // Blocker 1 follow-up: a missing reviewer model gets an explicit,
      // named, confirmable action right here -- not just descriptive
      // text. The actual click/confirm/fetch wiring lives in shell.js
      // (mountLauncherReadiness), which is DOM/fetch-dependent and
      // verified live in a real browser; this function stays pure and
      // Node-testable, so it only marks the action via data attributes.
      if (id === "reviewer-model" && model) {
        const btn = el("button", {
          type: "button", className: "btn-ghost",
          "data-action": "pull-reviewer-model", "data-model": model,
        }, [`Pull configured reviewer model (${model})`]);
        li.appendChild(btn);
      }
      return li;
    });
    children.push(el("ul", { className: "launcher-readiness-missing" }, items));
  }
  return el("div", { className: "launcher-readiness", role: "status" }, children);
}

/** Pure mapping from the `/api/launcher/readiness` JSON response onto
    `renderLauncherReadiness`'s props -- keeps app.js's fetch/mount glue to
    a single `fetch()` call with nothing else left to get wrong. `model`
    and `repositoryId` pass through (unlike the other fields, not coerced
    to a default) so the pull-model action can name the exact model and
    the mount glue knows which repository to act on. */
export function buildLauncherReadinessViewModel(apiResponse) {
  return {
    dashboardReady: Boolean(apiResponse.dashboardReady),
    runReady: Boolean(apiResponse.runReady),
    missing: Array.isArray(apiResponse.missing) ? apiResponse.missing : [],
    model: apiResponse.model || null,
    repositoryId: apiResponse.repositoryId ?? null,
  };
}
