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
import * as attentionPage from "./pages/attention.js";

const _PAGE_MODULES = {
  home: (root, params, ctx) => homePage.render(root, params, ctx),
  repositories: (root, params, ctx) => repositoriesPage.render(root, params, ctx),
  "repository-add": (root) => repositoriesPage.renderAdd(root),
  "repository-overview": (root, params, ctx) => repositoryDetailPage.render(root, params, ctx),
  attention: (root, params, ctx) => attentionPage.render(root, params, ctx),
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

  function renderCurrentRoute() {
    if (!pageRoot) return;
    if (!currentMatch) {
      renderNotFound(pageRoot);
      return;
    }
    const pageFn = _PAGE_MODULES[currentMatch.name];
    if (pageFn) pageFn(pageRoot, currentMatch.params, { coordinator });
    else renderNotYetAvailable(pageRoot, currentMatch.name);
  }

  createRouter({
    onNavigate(match, location) {
      currentMatch = match;
      if (navList) renderRailNav(navList, location.pathname);
      document.title = match ? `${match.name.replace(/-/g, " ")} — Draindeck Dashboard`
        : "Not found — Draindeck Dashboard";

      renderCurrentRoute();
      // Move focus to the main landmark on a real route change so
      // keyboard/AT users land at the new content -- but not on the very
      // first dispatch (the page just loaded; stealing focus from
      // wherever the browser already put it would be disorienting).
      if (!firstDispatch && mainContent) mainContent.focus();
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
      // Targeted per-resource refetch is a later polish pass (docs/27
      // SS9.3); re-running the current route's own render is a correct,
      // if less surgical, baseline -- each page's own coordinator-backed
      // fetches already supersede any still-in-flight request, so a
      // rapid run of invalidations never races itself.
      renderCurrentRoute();
    },
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
