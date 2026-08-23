"use strict";
// Shared "indexed views are still preparing / a snapshot exists but is
// stale/rebuilding" rendering (docs/27 SS3.2 decision 9), reused across
// every repository-scoped explorer/detail page so the exact wording and
// markup stay identical everywhere this state can occur.
import { ApiError } from "./api.js";
import { el } from "./dom.js";

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

/** A dismissible-free, always-visible banner for a page whose data is
    being served stale/rebuilding (docs/27 SS3.2 decision 9's "labelled
    stale/rebuilding" -- data stays on screen, just honestly labelled). */
export function staleBanner() {
  return el("p", { className: "state-panel state-panel--warning", role: "status" }, [STALE_TEXT]);
}

/** The cross-repository counterpart: never blocks (docs/27 SS3.2 decision
    9), just discloses that the aggregate below doesn't yet reflect every
    repository. */
export function projectionIncompleteBanner() {
  return el("p", { className: "state-panel state-panel--warning", role: "status" },
    [PROJECTION_INCOMPLETE_TEXT]);
}
