"use strict";
// The persistent shell: forest rail (8 stable destinations), utility bar
// theme control, and tablet-width expand/collapse toggle (docs/27 SS9.1,
// DESIGN.md Navigation). Every rail link keeps a visible short label at
// every width -- collapsing to 72px never hides it behind a tooltip.
import { el, text } from "../dom.js";
import { loadThemePreference, saveThemePreference, themeAttributeFor } from "../state.js";

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
