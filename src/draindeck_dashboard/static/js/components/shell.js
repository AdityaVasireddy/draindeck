"use strict";
// The persistent shell: forest rail (8 stable destinations), utility bar
// theme control, and tablet-width expand/collapse toggle (docs/27 SS9.1,
// DESIGN.md Navigation). Every rail link keeps a visible short label at
// every width -- collapsing to 72px never hides it behind a tooltip.
import { apiFetch } from "../api.js";
import { clear, el, text } from "../dom.js";
import { buildLauncherReadinessViewModel, renderLauncherReadiness } from "../readiness.js";
import { loadThemePreference, saveThemePreference, themeAttributeFor } from "../state.js";
import { openDialog } from "./dialog.js";

export const RAIL_DESTINATIONS = [
  { href: "/", label: "Home", icon: "⌂" },
  { href: "/repositories", label: "Repositories", icon: "▦" },
  { href: "/attention", label: "Attention", icon: "⚠" },
  { href: "/runs", label: "Runs", icon: "▶" },
  { href: "/issues", label: "Issues", icon: "⚑" },
  { href: "/executions", label: "Executions", icon: "⚙" },
  { href: "/evidence", label: "Evidence", icon: "☷" },
  { href: "/about", label: "About", icon: "ⓘ" },
];

export function isActiveRoute(pathname, href) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function renderRailNav(navListEl, pathname) {
  navListEl.textContent = "";
  for (const dest of RAIL_DESTINATIONS) {
    const active = isActiveRoute(pathname, dest.href);
    const link = el("a", {
      href: dest.href,
      "aria-current": active ? "page" : null,
    }, [
      el("span", { className: "rail-icon", "aria-hidden": "true" }, [dest.icon]),
      el("span", { className: "rail-label" }, [dest.label]),
    ]);
    navListEl.appendChild(el("li", null, [link]));
  }
}

function applyTheme(preference) {
  const attr = themeAttributeFor(preference);
  if (attr) document.documentElement.setAttribute("data-theme", attr);
  else document.documentElement.removeAttribute("data-theme");
}

const _THEME_CYCLE = ["system", "light", "dark"];
const _THEME_BUTTON_LABEL = { system: "Theme: System", light: "Theme: Light", dark: "Theme: Dark" };

export function initThemeControl(buttonEl) {
  let preference = loadThemePreference(window.localStorage);
  applyTheme(preference);
  buttonEl.textContent = _THEME_BUTTON_LABEL[preference];
  buttonEl.setAttribute("aria-label", `Theme control, currently ${preference}. Activate to change.`);

  buttonEl.addEventListener("click", () => {
    const next = _THEME_CYCLE[(_THEME_CYCLE.indexOf(preference) + 1) % _THEME_CYCLE.length];
    preference = saveThemePreference(window.localStorage, next);
    applyTheme(preference);
    buttonEl.textContent = _THEME_BUTTON_LABEL[preference];
    buttonEl.setAttribute("aria-label", `Theme control, currently ${preference}. Activate to change.`);
  });
}

export function initRailExpandToggle(toggleEl, railEl) {
  toggleEl.addEventListener("click", () => {
    const expanded = railEl.classList.toggle("is-expanded");
    toggleEl.setAttribute("aria-pressed", String(expanded));
    toggleEl.textContent = expanded ? "Collapse" : "Expand";
  });
}

export function updateConnectionStatus(statusEl, statusText) {
  statusEl.textContent = statusText;
}

/** Fetches /api/launcher/readiness and (re)renders the always-visible
    Dashboard-ready/Run-ready region in the utility bar (docs/32 review
    Blocker 3). Informational only -- a network/API failure here leaves
    the previous render in place rather than breaking the rest of the
    shell, since the region is a status indicator, not load-bearing UI.
    `repoId`, when the current route names one (docs/32 review Blocker 2
    follow-up), scopes the check to that repository -- omitting it would
    silently show whichever repository the API auto-selects (the first
    with a canonical config), which is misleading on any page actually
    viewing a DIFFERENT registered repository. */
export async function mountLauncherReadiness(container, { coordinator, repoId }) {
  if (!container) return;
  const path = repoId
    ? `/api/launcher/readiness?repoId=${encodeURIComponent(repoId)}`
    : "/api/launcher/readiness";
  let body;
  try {
    body = await coordinator.fetch("launcher-readiness", path);
  } catch (e) {
    return;
  }
  if (!body) return; // superseded by a newer fetch, or aborted
  const vm = buildLauncherReadinessViewModel(body);
  clear(container);
  container.appendChild(renderLauncherReadiness(vm));

  const pullBtn = container.querySelector('[data-action="pull-reviewer-model"]');
  if (pullBtn && vm.repositoryId != null) {
    pullBtn.addEventListener("click", () => {
      _confirmAndPullReviewerModel(container, { coordinator, repoId: vm.repositoryId }, vm.model);
    });
  }
}

/** Blocker 1 follow-up: "Pull configured reviewer model" requires its own
    explicit confirmation (a model pull can be a multi-gigabyte download)
    before the Dashboard ever calls the pull endpoint -- mirrors the
    existing openDialog confirm pattern used for starting a run
    (pages/run-control.js). */
function _confirmAndPullReviewerModel(container, ctx, model) {
  const { close } = openDialog({
    titleText: "Pull configured reviewer model",
    bodyNodes: [
      el("p", null, [
        "This downloads the reviewer model configured for this repository via ",
        el("code", null, [`ollama pull ${model}`]),
        ". This may be a large download.",
      ]),
    ],
    actions: [
      { label: "Cancel", className: "btn-ghost" },
      {
        label: "Pull model", className: "btn btn-primary", autofocus: true,
        onClick: () => {
          close();
          _runReviewerModelPull(container, ctx, model);
        },
      },
    ],
  });
}

function _renderPullStatusLine(container, statusText) {
  let line = container.querySelector("[data-model-pull-status]");
  if (!line) {
    line = el("p", { className: "text-muted", role: "status", "data-model-pull-status": "" });
    container.appendChild(line);
  }
  line.textContent = statusText;
}

async function _runReviewerModelPull(container, ctx, model) {
  _renderPullStatusLine(container, `Pulling ${model}...`);
  try {
    await apiFetch(`/api/repositories/${ctx.repoId}/pull-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) {
    _renderPullStatusLine(container, `Failed to start pulling ${model}: ${e.message}`);
    return;
  }
  await _pollReviewerModelPull(container, ctx, model);
}

// Polls at a fixed 3s interval, up to 30 minutes -- long enough for a
// multi-gigabyte model pull, without polling so tightly it floods the
// Dashboard's own process. Success re-mounts the whole region (refreshes
// readiness, per Blocker 1's requirement); failure is shown honestly with
// the pull's own reported error, never silently dropped.
const _PULL_POLL_INTERVAL_MS = 3000;
const _PULL_POLL_MAX_ATTEMPTS = 600;

async function _pollReviewerModelPull(container, ctx, model) {
  for (let attempt = 0; attempt < _PULL_POLL_MAX_ATTEMPTS; attempt += 1) {
    let status;
    try {
      status = await apiFetch(`/api/repositories/${ctx.repoId}/pull-model`);
    } catch (e) {
      _renderPullStatusLine(container, `Failed to check pull status: ${e.message}`);
      return;
    }
    if (status.status === "success") {
      await mountLauncherReadiness(container, ctx);
      return;
    }
    if (status.status === "failed") {
      _renderPullStatusLine(container, `Failed to pull ${model}: ${status.error || "unknown error"}`);
      return;
    }
    await new Promise((resolve) => { setTimeout(resolve, _PULL_POLL_INTERVAL_MS); });
  }
  _renderPullStatusLine(container, `Still pulling ${model}...`);
}
