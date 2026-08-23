"use strict";
// Safe node creation and keyed-list patching (docs/27 SS9.3). Observed
// text is assigned through textContent/text nodes ONLY -- no function
// here ever accepts or assembles an HTML string. Keyed sync patches
// existing rows in place rather than clearing and recreating them, so
// focus/scroll on an unaffected row survives a background refresh.

/** Creates `tag` with attributes from `props` (never `innerHTML`,
    `style`, or an `on*` attribute -- use addEventListener) and appends
    `children` (strings become text nodes; null/undefined are skipped). */
export function el(tag, props, children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined) continue;
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else if (key.startsWith("aria-") || key.startsWith("data-") || key === "role"
               || key === "for" || key === "tabindex" || key === "type" || key === "href") {
        node.setAttribute(key, String(value));
      } else {
        node[key] = value;
      }
    }
  }
  for (const child of children || []) {
    if (child === null || child === undefined) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function text(value) {
  return document.createTextNode(value == null ? "" : String(value));
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** A machine-readable timestamp paired with its visible label -- never a
    relative label without the exact absolute time available (docs/27
    SS10). `absoluteText`/`relativeText` come from format.js. */
export function timeElement(iso, absoluteText, relativeText) {
  const time = document.createElement("time");
  if (iso) time.setAttribute("datetime", iso);
  time.textContent = relativeText ? `${relativeText} (${absoluteText})` : (absoluteText || "unknown");
  return time;
}

/** A status chip: text + icon/shape, never color alone (DESIGN.md "The
    Annotation Rule"). `icon` is a short glyph/letter rendered
    aria-hidden; the text itself always carries the meaning. */
export function statusChip(labelText, tone, icon) {
  const chip = el("span", { className: `chip chip--${tone}` });
  if (icon) {
    const glyph = el("span", { "aria-hidden": "true", className: "chip-icon" }, [icon]);
    chip.appendChild(glyph);
  }
  chip.appendChild(text(labelText));
  return chip;
}

/** Keyed incremental list sync: matches existing `[data-key]` children
    against `items` by `keyFn`, updates each in place via `renderFn(el,
    item)`, removes stragglers, appends new rows, and reorders via
    insertBefore only when order actually changed. Renders `emptyMessage`
    as a single placeholder child when `items` is empty. `containerTag`
    defaults to "li" (the common case: an existing <ul>/<ol> list). */
export function syncList(listEl, items, keyFn, renderFn, emptyMessage, containerTag) {
  const tag = containerTag || "li";
  const existing = new Map();
  for (const child of Array.from(listEl.children)) {
    const key = child.getAttribute("data-key");
    if (key !== null) existing.set(key, child);
  }
  listEl.querySelectorAll("[data-empty-placeholder]").forEach((node) => node.remove());

  if (!items || items.length === 0) {
    for (const child of existing.values()) child.remove();
    const placeholder = el(tag, { className: "empty-state", "data-empty-placeholder": "" },
      [emptyMessage]);
    listEl.appendChild(placeholder);
    return;
  }

  let previousEl = null;
  const seen = new Set();
  for (const item of items) {
    const key = String(keyFn(item));
    seen.add(key);
    let node = existing.get(key);
    if (!node) {
      node = document.createElement(tag);
      node.setAttribute("data-key", key);
    }
    renderFn(node, item);
    if (previousEl === null) {
      if (listEl.firstChild !== node) listEl.insertBefore(node, listEl.firstChild);
    } else if (previousEl.nextSibling !== node) {
      listEl.insertBefore(node, previousEl.nextSibling);
    }
    previousEl = node;
  }
  for (const [key, node] of existing) {
    if (!seen.has(key)) node.remove();
  }
}
