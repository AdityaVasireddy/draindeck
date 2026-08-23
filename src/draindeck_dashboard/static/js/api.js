"use strict";
// Typed fetch errors, and per-key request coordination so a newer
// request for the same resource always supersedes and discards an
// older still-in-flight one (docs/27 SS9.2/SS9.3) -- late responses
// never overwrite a newer route/filter's rendered state.

export class ApiError extends Error {
  constructor(message, { code, status } = {}) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function apiFetch(path, options) {
  let resp;
  try {
    resp = await fetch(path, options);
  } catch (e) {
    if (e && e.name === "AbortError") throw e; // let the coordinator suppress this
    throw new ApiError(`network error: ${e && e.message ? e.message : e}`, { code: "NETWORK_ERROR" });
  }
  let body = null;
  try {
    body = await resp.json();
  } catch (e) {
    body = null;
  }
  if (!resp.ok) {
    const message = (body && body.error && body.error.message) || `request failed (${resp.status})`;
    throw new ApiError(message, { code: body && body.error && body.error.code, status: resp.status });
  }
  return body;
}

/** Coordinates concurrent fetches keyed by an arbitrary string (usually
    "route:resource"). Starting a new fetch under the same key aborts any
    still-in-flight fetch for that key; a stale response (aborted, or
    superseded before it resolved) is suppressed -- callers get `undefined`
    back instead of stale data, never an exception for the abort itself. */
export function createRequestCoordinator() {
  const controllers = new Map();
  return {
    async fetch(key, path, options) {
      const previous = controllers.get(key);
      if (previous) previous.abort();
      const controller = new AbortController();
      controllers.set(key, controller);
      try {
        const result = await apiFetch(path, { ...(options || {}), signal: controller.signal });
        if (controllers.get(key) !== controller) return undefined; // superseded mid-flight
        return result;
      } catch (e) {
        if (controller.signal.aborted) return undefined; // suppressed, not an error
        throw e;
      } finally {
        if (controllers.get(key) === controller) controllers.delete(key);
      }
    },
    abortAll() {
      for (const controller of controllers.values()) controller.abort();
      controllers.clear();
    },
  };
}
