"use strict";
// Boot: mounts the persistent shell (rail nav + theme control) and
// dispatches each route to its page module (docs/27 SS9.1/SS9.2). A
// route matched by the router but not yet backed by a page module
// (Units 10-14 still to come) renders an honest "not yet available"
// state rather than a blank page or a JS error.
import { createRequestCoordinator } from "./api.js";
import { initRailExpandToggle, initThemeControl, renderRailNav, updateConnectionStatus } from
  "./components/shell.js";
import { initGlobalSearch } from "./components/search.js";
import { clear, el } from "./dom.js";
import { createRouter } from "./router.js";
import { connectChangeStream, connectionStatusLabel } from "./stream.js";
import * as homePage from "./pages/home.js";
import * as repositoriesPage from "./pages/repositories.js";
import * as repositoryDetailPage from "./pages/repository-detail.js";
import * as targetConfigurationPage from "./pages/target-configuration.js";
import * as attentionPage from "./pages/attention.js";
import * as runsPage from "./pages/runs.js";
import * as issuesPage from "./pages/issues.js";
import * as executionsPage from "./pages/executions.js";
import * as evidencePage from "./pages/evidence.js";
import * as aboutPage from "./pages/about.js";

// Each entry is {render, refresh}. `render` mounts the page from scratch
// (a real navigation) -- `refresh` is called instead on an SSE
// invalidation and MUST reuse the existing DOM shell (never clear(root))
// so an in-progress SSE update never steals focus/scroll out from under
// the user the way a full re-render would. A page without its own
// lighter refresh path falls back to `render` (still correct, just not
// focus-preserving) rather than being omitted.
const _PAGE_MODULES = {
  home: { render: (root, params, ctx) => homePage.render(root, params, ctx),
         refresh: (root, params, ctx) => homePage.refresh(root, params, ctx) },
  repositories: { render: (root, params, ctx) => repositoriesPage.render(root, params, ctx),
                 refresh: (root, params, ctx) => repositoriesPage.refresh(root, params, ctx) },
  "repository-add": { render: (root) => repositoriesPage.renderAdd(root) },
  "repository-new-target": { render: (root, params, ctx) => targetConfigurationPage.renderNew(root, params, ctx) },
  "repository-configuration": { render: (root, params, ctx) => targetConfigurationPage.renderEdit(root, params, ctx) },
  "repository-overview": { render: (root, params, ctx) => repositoryDetailPage.render(root, params, ctx) },
  attention: { render: (root, params, ctx) => attentionPage.render(root, params, ctx),
              refresh: (root, params, ctx) => attentionPage.refresh(root, params, ctx) },
  runs: { render: (root, params, ctx) => runsPage.render(root, params, ctx),
         refresh: (root, params, ctx) => runsPage.refresh(root, params, ctx) },
  "repository-runs": { render: (root, params, ctx) => runsPage.render(root, params, ctx),
                       refresh: (root, params, ctx) => runsPage.refresh(root, params, ctx) },
  "run-detail": { render: (root, params) => runsPage.renderDetail(root, params) },
  issues: { render: (root, params, ctx) => issuesPage.render(root, params, ctx),
           refresh: (root, params, ctx) => issuesPage.refresh(root, params, ctx) },
  "repository-issues": { render: (root, params, ctx) => issuesPage.render(root, params, ctx),
                         refresh: (root, params, ctx) => issuesPage.refresh(root, params, ctx) },
  "issue-detail": { render: (root, params) => issuesPage.renderDetail(root, params) },
  executions: { render: (root, params, ctx) => executionsPage.render(root, params, ctx),
               refresh: (root, params, ctx) => executionsPage.refresh(root, params, ctx) },
  "repository-executions": { render: (root, params, ctx) => executionsPage.render(root, params, ctx),
                             refresh: (root, params, ctx) => executionsPage.refresh(root, params, ctx) },
  "execution-detail": { render: (root, params) => executionsPage.renderDetail(root, params) },
  evidence: { render: (root, params, ctx) => evidencePage.render(root, params, ctx),
             refresh: (root, params, ctx) => evidencePage.refresh(root, params, ctx) },
  "repository-evidence": { render: (root, params, ctx) => evidencePage.render(root, params, ctx),
                           refresh: (root, params, ctx) => evidencePage.refresh(root, params, ctx) },
  "evidence-detail": { render: (root, params) => evidencePage.renderDetail(root, params) },
  about: { render: (root, params, ctx) => aboutPage.render(root, params, ctx) },
};

function renderNotYetAvailable(root, routeName) {
  clear(root);
  root.appendChild(el("div", { className: "state-panel" }, [
    el("p", { className: "state-panel-title" }, ["This view is not available yet."]),
    el("p", { className: "text-muted" }, [`"${routeName}" is part of a later build stage.`]),
    el("a", { href: "/", className: "btn-ghost" }, ["Return home"]),
  ]));
}

function renderNotFound(root) {
  clear(root);
  root.appendChild(el("div", { className: "state-panel state-panel--error" }, [
    el("p", { className: "state-panel-title" }, ["Page not found."]),
    el("a", { href: "/", className: "btn-ghost" }, ["Return home"]),
  ]));
}

function boot() {
  const navList = document.getElementById("rail-nav-list");
  const pageRoot = document.getElementById("page-root");
  const mainContent = document.getElementById("main-content");
  const coordinator = createRequestCoordinator();

  const themeButton = document.getElementById("theme-toggle");
  if (themeButton) initThemeControl(themeButton);

  const railExpandToggle = document.getElementById("rail-expand-toggle");
  const rail = document.getElementById("app-rail");
  if (railExpandToggle && rail) initRailExpandToggle(railExpandToggle, rail);

  const searchInput = document.getElementById("global-search-input");
  const searchListbox = document.getElementById("global-search-listbox");
  if (searchInput && searchListbox) initGlobalSearch(searchInput, searchListbox, { coordinator });

  let firstDispatch = true;
  let currentMatch = null;
  let router = null;

  function renderCurrentRoute() {
    if (!pageRoot) return;
    if (!currentMatch) {
      renderNotFound(pageRoot);
      return;
    }
    const entry = _PAGE_MODULES[currentMatch.name];
    const ctx = { coordinator, navigate: (path, options) => router.navigate(path, options) };
    if (entry) entry.render(pageRoot, currentMatch.params, ctx);
    else renderNotYetAvailable(pageRoot, currentMatch.name);
  }

  // Called on an SSE invalidation, never on a real navigation. Reuses the
  // shell `render()` already built for the current route rather than
  // tearing it down -- a page with its own `refresh` only re-fetches and
  // syncList-updates its dynamic content, so a user's mid-scroll position,
  // focused row link, or open filter stays exactly where it was. A page
  // without a lighter `refresh` path falls back to the full `render()`
  // (correct, just not focus-preserving).
  function refreshCurrentRoute() {
    if (!pageRoot || !currentMatch) return;
    const entry = _PAGE_MODULES[currentMatch.name];
    if (!entry) return;
    const ctx = { coordinator, navigate: (path, options) => router.navigate(path, options) };
    if (entry.refresh) entry.refresh(pageRoot, currentMatch.params, ctx);
    else entry.render(pageRoot, currentMatch.params, ctx);
  }

  router = createRouter({
    onNavigate(match, location, options) {
      currentMatch = match;
      if (navList) renderRailNav(navList, location.pathname);
      document.title = match ? `${match.name.replace(/-/g, " ")} — Draindeck Dashboard`
        : "Not found — Draindeck Dashboard";

      renderCurrentRoute();
      // Move focus to the main landmark on a real route change so
      // keyboard/AT users land at the new content -- but not on the very
      // first dispatch (the page just loaded; stealing focus from
      // wherever the browser already put it would be disorienting) and
      // not when a same-page filter/toggle/search action explicitly asks
      // to keep focus where the user already is (docs/27 SS9.2; a page
      // module requests this via `ctx.navigate(path, {preserveFocus:
      // true})` instead of a plain link click or browser back/forward,
      // both of which remain real navigations that do focus main).
      const preserveFocus = options && options.preserveFocus;
      if (!firstDispatch && !preserveFocus && mainContent) mainContent.focus();
      firstDispatch = false;
    },
  });

  const statusEl = document.getElementById("connection-status");
  connectChangeStream({
    url: "/api/events",
    onStatusChange(status) {
      if (statusEl) updateConnectionStatus(statusEl, connectionStatusLabel(status));
    },
    onInvalidate() {
      // refresh (not render): reuses the mounted shell and only updates
      // dynamic content in place, so focus/scroll survive a targeted SSE
      // update (docs/27 SS9.3). Each page's own coordinator-backed
      // fetches already supersede any still-in-flight request, so a rapid
      // run of invalidations never races itself.
      refreshCurrentRoute();
    },
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
