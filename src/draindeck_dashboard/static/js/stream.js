"use strict";
// SSE connection state and invalidation handling (docs/27 SS5.1, SS6.4,
// SS9.3). "Updates connected" describes only the browser's SSE stream --
// never a runtime process. entityType is extensible: v2 adds "attention",
// "repository_health", and "read_model"; a system-wide change carries
// the reserved repositoryId 0 (real repository IDs start at one).

export const SYSTEM_REPOSITORY_ID = 0;

export const CONNECTION_STATUS = Object.freeze({
  CONNECTING: "connecting",
  CONNECTED: "connected",
  RECONNECTING: "reconnecting",
  RESYNCING: "resyncing",
});

const _STATUS_LABELS = {
  [CONNECTION_STATUS.CONNECTED]: "Updates connected",
  [CONNECTION_STATUS.CONNECTING]: "Connecting to updates",
  [CONNECTION_STATUS.RECONNECTING]: "Reconnecting to updates",
  [CONNECTION_STATUS.RESYNCING]: "Refreshing snapshot",
};

/** Exact connection-status text (docs/27 SS5.1) -- never claims a
    Draindeck runtime process is running. */
export function connectionStatusLabel(status) {
  return _STATUS_LABELS[status] || _STATUS_LABELS[CONNECTION_STATUS.CONNECTING];
}

export function isSystemWideChange(change) {
  return change && change.repositoryId === SYSTEM_REPOSITORY_ID;
}

/** Coalesces rapid `change` events over a short window, keyed by
    (repositoryId, entityType, entityId) so only the LATEST change per
    identity survives -- a burst of updates to the same row never queues
    N redundant refetches (docs/27 SS9.3). Fires `onFlush(changes)` at
    most once per window with the deduplicated set. */
export function createChangeCoalescer(onFlush, windowMs) {
  const pending = new Map();
  let timer = null;
  const win = windowMs == null ? 250 : windowMs;

  function flush() {
    const changes = Array.from(pending.values());
    pending.clear();
    timer = null;
    if (changes.length > 0) onFlush(changes);
  }

  return {
    push(change) {
      const key = `${change.repositoryId}:${change.entityType}:${change.entityId ?? ""}`;
      pending.set(key, change);
      if (timer === null) timer = setTimeout(flush, win);
    },
    flushNow: flush,
    pendingCount: () => pending.size,
  };
}

/** A recurring callback (e.g. the 30-second time-derived attention/lease
    refresh docs/27 SS6.4 requires even without a missed invalidation).
    Returns {stop}. */
export function createPeriodicRefresh(callback, intervalMs) {
  const interval = intervalMs == null ? 30000 : intervalMs;
  const timer = setInterval(callback, interval);
  return { stop: () => clearInterval(timer) };
}

/** Wraps a browser EventSource against `/api/events`, translating its
    open/error/message events into CONNECTION_STATUS transitions and
    routing `change`/`resync` payloads through a coalescer. Real
    EventSource wiring -- verified live in a browser, not simulated in
    plain Node (docs/27 SS13.4). `EventSourceImpl` is injectable so a
    future test harness with a fake EventSource could still exercise
    this without a real browser. */
export function connectChangeStream({ url, EventSourceImpl, onStatusChange, onInvalidate,
                                     coalesceWindowMs }) {
  const Impl = EventSourceImpl || window.EventSource;
  const coalescer = createChangeCoalescer(onInvalidate, coalesceWindowMs);
  let source = null;
  let stopped = false;

  function open() {
    if (stopped) return;
    onStatusChange(CONNECTION_STATUS.CONNECTING);
    source = new Impl(url);

    source.addEventListener("open", () => onStatusChange(CONNECTION_STATUS.CONNECTED));
    source.addEventListener("error", () => {
      if (!stopped) onStatusChange(CONNECTION_STATUS.RECONNECTING);
    });
    source.addEventListener("change", (event) => {
      let change;
      try {
        change = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      coalescer.push(change);
    });
    source.addEventListener("resync", () => {
      onStatusChange(CONNECTION_STATUS.RESYNCING);
      coalescer.flushNow();
      onInvalidate([{ repositoryId: SYSTEM_REPOSITORY_ID, entityType: "resync" }]);
      // The resync event carries no id, so the browser's own
      // Last-Event-ID stays stale -- reconnecting the SAME source would
      // just repeat it forever. Close and open a fresh one instead.
      source.close();
      window.setTimeout(open, 100);
    });
  }

  open();
  return {
    stop() {
      stopped = true;
      if (source) source.close();
    },
  };
}
