"use strict";
// Client-side routing via the History API, matching the same approved
// UI route patterns app.py's server-side allowlist serves (docs/27 SS4,
// SS9.2). Native links keep working (open-in-new-tab, copy-link,
// middle-click) -- only a plain same-origin left-click is intercepted
// and enhanced into a pushState navigation.

export const ROUTES = [
  { pattern: "/", name: "home" },
  { pattern: "/repositories", name: "repositories" },
  { pattern: "/repositories/new", name: "repository-add" },
  { pattern: "/repositories/new-target", name: "repository-new-target" },
  { pattern: "/repositories/:repoId/configuration", name: "repository-configuration" },
  { pattern: "/repositories/:repoId", name: "repository-overview" },
  { pattern: "/repositories/:repoId/runs", name: "repository-runs" },
  { pattern: "/repositories/:repoId/runs/:runId", name: "run-detail" },
  { pattern: "/repositories/:repoId/issues", name: "repository-issues" },
  { pattern: "/repositories/:repoId/issues/:issueId", name: "issue-detail" },
  { pattern: "/repositories/:repoId/executions", name: "repository-executions" },
  { pattern: "/repositories/:repoId/executions/:executionId", name: "execution-detail" },
  { pattern: "/repositories/:repoId/evidence", name: "repository-evidence" },
  { pattern: "/repositories/:repoId/evidence/:evidenceId", name: "evidence-detail" },
  { pattern: "/attention", name: "attention" },
  { pattern: "/runs", name: "runs" },
  { pattern: "/issues", name: "issues" },
  { pattern: "/executions", name: "executions" },
  { pattern: "/evidence", name: "evidence" },
  { pattern: "/about", name: "about" },
];

function compilePattern(pattern) {
  const paramNames = [];
  const escaped = pattern
    .split("/")
    .map((segment) => {
      if (segment.startsWith(":")) {
        paramNames.push(segment.slice(1));
        return "([^/]+)";
      }
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { regex: new RegExp(`^${escaped}/?$`), paramNames };
}

/** Matches `pathname` against `routes` (in order -- first match wins,
    same as the server-side allowlist's literal-before-parameterized
    ordering). Returns `{name, params, pattern}` or null. Pure and
    dependency-free, so it's testable without a real DOM. */
export function matchRoute(pathname, routes) {
  const list = routes || ROUTES;
  for (const route of list) {
    const { regex, paramNames } = compilePattern(route.pattern);
    const match = pathname.match(regex);
    if (match) {
      const params = {};
      paramNames.forEach((name, i) => {
        params[name] = decodeURIComponent(match[i + 1]);
      });
      return { name: route.name, params, pattern: route.pattern };
    }
  }
  return null;
}

function isPlainLeftClick(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey
    && !event.shiftKey && !event.altKey;
}

/** Wires document-level click interception and popstate handling.
    `onNavigate(match, location)` is called on boot and on every
    subsequent navigation; `match` is null for an unknown path (the page
    layer renders a not-found state; the server would 404 on a real
    reload of the same URL). Browser-verified (needs a real DOM/History
    API) rather than Node-tested. */
export function createRouter({ routes, onNavigate, documentImpl, windowImpl }) {
  const doc = documentImpl || document;
  const win = windowImpl || window;

  function dispatch(options) {
    const match = matchRoute(win.location.pathname, routes);
    onNavigate(match, win.location, options);
  }

  function navigate(path, options) {
    const replace = options && options.replace;
    const current = win.location.pathname + win.location.search;
    if (path === current) {
      dispatch(options);
      return;
    }
    if (replace) win.history.replaceState({}, "", path);
    else win.history.pushState({}, "", path);
    dispatch(options);
  }

  function handleClick(event) {
    if (event.defaultPrevented || !isPlainLeftClick(event)) return;
    const anchor = event.target.closest && event.target.closest("a[href]");
    if (!anchor) return;
    if (anchor.hasAttribute("download")) return;
    if (anchor.target && anchor.target !== "" && anchor.target !== "_self") return;
    const url = new URL(anchor.getAttribute("href"), win.location.href);
    if (url.origin !== win.location.origin) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  }

  doc.addEventListener("click", handleClick);
  win.addEventListener("popstate", dispatch);
  dispatch();

  return {
    navigate,
    dispatch,
    matchRoute: (pathname) => matchRoute(pathname, routes),
    destroy() {
      doc.removeEventListener("click", handleClick);
      win.removeEventListener("popstate", dispatch);
    },
  };
}
