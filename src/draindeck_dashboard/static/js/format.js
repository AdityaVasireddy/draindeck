"use strict";
// Exact labels/dates/identifiers (docs/27 SS5, SS9.1). Pure functions --
// no DOM access -- so they stay unit-testable from plain Node.

export const NO_CONTROLLED_FINISH_TEXT = "no controlled finish observed";
export const RUN_METADATA_UNAVAILABLE_TEXT = "run metadata unavailable (legacy/ambiguous)";
export const NOT_YET_OBSERVED_TEXT = "Not yet observed";
export const NO_INCONSISTENCY_TEXT = "No inconsistency observed";

/** Final path segment, tolerant of both "\\" and "/" separators. */
export function displayName(path) {
  if (typeof path !== "string" || path.length === 0) return "";
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const idx = normalized.lastIndexOf("/");
  return idx === -1 ? normalized : normalized.slice(idx + 1);
}

/** Locale date/time string for the visible label half of a <time> pair. */
export function formatAbsoluteTimestamp(iso) {
  if (typeof iso !== "string" || iso.length === 0) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/** Coarse relative-time text. Never call this without ALSO rendering the
    exact absolute timestamp alongside it (docs/27 SS10) -- this function
    only produces the label half. */
export function formatRelativeTime(iso, nowMs) {
  if (typeof iso !== "string" || iso.length === 0) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const now = typeof nowMs === "number" ? nowMs : Date.now();
  const diffSeconds = Math.max(0, Math.round((now - then) / 1000));
  if (diffSeconds < 5) return "just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const minutes = Math.round(diffSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

const _AVAILABILITY_LABELS = {
  AVAILABLE: "Available", EMPTY: "Empty", NOT_INITIALIZED: "Not initialized",
  OFFLINE: "Offline",
};

/** Exact availability label; null/undefined -> "Not yet observed"
    (docs/27 SS5.2) -- never invents a fifth state. */
export function availabilityLabel(value) {
  if (value === null || value === undefined) return NOT_YET_OBSERVED_TEXT;
  return _AVAILABILITY_LABELS[value] || value;
}

/** Run outcome display text -- never "Running"/"Active" (docs/27 SS5.3). */
export function runDisplayOutcome(outcome) {
  return outcome || NO_CONTROLLED_FINISH_TEXT;
}

/** Inconsistency label -- never "verified"/"valid" (docs/27 SS5.3). */
export function inconsistencyLabel(inconsistent) {
  return inconsistent ? "Inconsistency observed" : NO_INCONSISTENCY_TEXT;
}

/** Run metadata display text, honoring the exact legacy/ambiguous
    fallback (docs/27 SS5.3) when unavailable. */
export function runMetadataText(runMetadata) {
  if (!runMetadata || !runMetadata.available) {
    return (runMetadata && runMetadata.message) || RUN_METADATA_UNAVAILABLE_TEXT;
  }
  const provider = runMetadata.engineProvider || "unknown engine";
  const model = runMetadata.engineModel || "unknown model";
  const outcome = runDisplayOutcome(runMetadata.outcome);
  return `${provider} / ${model} — ${outcome}`;
}

const _SEVERITY_ORDER = { critical: 0, warning: 1, information: 2 };

/** Closed severity sort key (docs/27 SS6.4: critical -> warning ->
    informational, then oldest first via a stable secondary sort by the
    caller). */
export function severityRank(severity) {
  return _SEVERITY_ORDER[severity] ?? 99;
}

/** One-based UI page number <-> zero-based API offset (docs/27 SS4). */
export function pageToOffset(page, pageSize) {
  const p = Math.max(1, Math.trunc(page) || 1);
  return (p - 1) * pageSize;
}

export function offsetToPage(offset, pageSize) {
  return Math.floor(offset / pageSize) + 1;
}
