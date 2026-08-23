"use strict";
// Boot: mounts the persistent shell (rail nav + theme control) around
// whatever page content the current route renders. Units 8-14 replace
// the legacy /app.js page logic below the shell with the real client
// router and page modules; this module owns only the chrome (docs/27
// SS9.1) so it is stable across that migration.
import { initRailExpandToggle, initThemeControl, renderRailNav } from "./components/shell.js";
import { createRouter } from "./router.js";

function boot() {
  const navList = document.getElementById("rail-nav-list");

  const themeButton = document.getElementById("theme-toggle");
  if (themeButton) initThemeControl(themeButton);

  const railExpandToggle = document.getElementById("rail-expand-toggle");
  const rail = document.getElementById("app-rail");
  if (railExpandToggle && rail) initRailExpandToggle(railExpandToggle, rail);

  // Route dispatch is wired now so History API navigation and the rail's
  // active-state work end-to-end; Units 9-14 replace #page-root's fixed
  // Part 2 markup with real per-route page modules driven from the same
  // `match` this callback already receives.
  createRouter({
    onNavigate(match, location) {
      if (navList) renderRailNav(navList, location.pathname);
      document.title = match ? `${match.name.replace(/-/g, " ")} — Draindeck Dashboard`
        : "Not found — Draindeck Dashboard";
    },
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
