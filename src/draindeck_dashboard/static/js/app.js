"use strict";
// Boot: mounts the persistent shell (rail nav + theme control) around
// whatever page content the current route renders. Units 8-14 replace
// the legacy /app.js page logic below the shell with the real client
// router and page modules; this module owns only the chrome (docs/27
// SS9.1) so it is stable across that migration.
import { initRailExpandToggle, initThemeControl, renderRailNav } from "./components/shell.js";

function boot() {
  const navList = document.getElementById("rail-nav-list");
  if (navList) renderRailNav(navList, window.location.pathname);

  const themeButton = document.getElementById("theme-toggle");
  if (themeButton) initThemeControl(themeButton);

  const railExpandToggle = document.getElementById("rail-expand-toggle");
  const rail = document.getElementById("app-rail");
  if (railExpandToggle && rail) initRailExpandToggle(railExpandToggle, rail);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
