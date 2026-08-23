"use strict";
// Small explicit UI/cache state (docs/27 SS9.2). The URL remains the
// source of truth for route/list state -- this module holds only
// transient, non-URL state: theme preference, connection status, and a
// bounded per-resource cache the API client/SSE layer coordinate through.

export const THEME_STORAGE_KEY = "draindeck-dashboard-theme";
const _VALID_THEMES = new Set(["system", "light", "dark"]);

/** Reads the stored theme preference, defaulting safely to "system" on
    absence or corruption (docs/27 SS9.2) -- pure function of the raw
    stored string so it's testable without a real localStorage. */
export function resolveStoredTheme(rawValue) {
  return _VALID_THEMES.has(rawValue) ? rawValue : "system";
}

/** The `data-theme` attribute value to apply to <html> for a given
    preference -- "system" means "let prefers-color-scheme decide",
    represented by removing the attribute entirely (null). */
export function themeAttributeFor(preference) {
  if (preference === "light" || preference === "dark") return preference;
  return null;
}

export function loadThemePreference(storage) {
  try {
    return resolveStoredTheme(storage.getItem(THEME_STORAGE_KEY));
  } catch (e) {
    return "system";
  }
}

export function saveThemePreference(storage, preference) {
  const safe = resolveStoredTheme(preference);
  try {
    storage.setItem(THEME_STORAGE_KEY, safe);
  } catch (e) {
    // Storage unavailable/full -- theme still applies for this session,
    // just doesn't persist. Never throw out of a preference change.
  }
  return safe;
}

/** A tiny store: get/set/subscribe. Used for state that several
    independently-mounted components need to react to (connection
    status, active repository selection context) without a framework. */
export function createStore(initial) {
  let value = initial;
  const listeners = new Set();
  return {
    get: () => value,
    set(next) {
      value = typeof next === "function" ? next(value) : next;
      for (const listener of listeners) listener(value);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
