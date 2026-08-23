"use strict";
// Global search: a labelled combobox/listbox pattern (docs/27 SS9.2) --
// debounced requests, Escape closes without moving focus, arrow
// navigation, Enter navigates. No advanced query syntax or search
// history is ever exposed (docs/27 SS7.1/SS15).
import { apiFetch } from "../api.js";
import { clear, el } from "../dom.js";

const _GROUP_ORDER = ["repositories", "issues", "runs", "executions", "evidence"];
const _GROUP_LABELS = {
  repositories: "Repositories", issues: "Issues", runs: "Runs",
  executions: "Executions", evidence: "Evidence",
};

export function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

/** Pure: flattens the grouped /api/search response into one ordered list
    (group order fixed, matching docs/27 SS7.1's five groups), each item
    tagged with which group it came from -- the shape the listbox and
    keyboard navigation both index into. */
export function flattenGroupedResults(groups) {
  const flat = [];
  for (const key of _GROUP_ORDER) {
    for (const item of (groups && groups[key]) || []) {
      flat.push({ ...item, group: key });
    }
  }
  return flat;
}

/** Pure: the next active index for Arrow Up/Down, wrapping at both ends;
    -1 (nothing active) advances to the first (Down) or last (Up) item. */
export function nextActiveIndex(current, total, direction) {
  if (total === 0) return -1;
  if (current < 0) return direction > 0 ? 0 : total - 1;
  return (current + direction + total) % total;
}

function renderResultsList(listEl, flatResults, activeIndex) {
  clear(listEl);
  let currentGroup = null;
  flatResults.forEach((item, index) => {
    if (item.group !== currentGroup) {
      currentGroup = item.group;
      listEl.appendChild(el("li", { role: "presentation", className: "search-group-label" },
        [_GROUP_LABELS[currentGroup] || currentGroup]));
    }
    const option = el("li", {
      role: "option", id: `search-option-${index}`,
      "aria-selected": String(index === activeIndex),
      className: index === activeIndex ? "search-option is-active" : "search-option",
    }, [
      el("a", { href: item.url, tabindex: "-1" }, [item.label]),
    ]);
    listEl.appendChild(option);
  });
}

/** Wires a text input + listbox into a working combobox. Browser-verified
    (needs a real DOM); the pure functions above are Node-tested. */
export function initGlobalSearch(inputEl, listboxEl, options) {
  const opts = options || {};
  const debounceMs = opts.debounceMs == null ? 200 : opts.debounceMs;
  const coordinator = opts.coordinator;

  let flatResults = [];
  let activeIndex = -1;
  let open = false;

  function closeList() {
    open = false;
    listboxEl.hidden = true;
    inputEl.setAttribute("aria-expanded", "false");
    inputEl.removeAttribute("aria-activedescendant");
  }

  function openList() {
    open = true;
    listboxEl.hidden = false;
    inputEl.setAttribute("aria-expanded", "true");
  }

  function setActive(index) {
    activeIndex = index;
    renderResultsList(listboxEl, flatResults, activeIndex);
    if (index >= 0) inputEl.setAttribute("aria-activedescendant", `search-option-${index}`);
    else inputEl.removeAttribute("aria-activedescendant");
  }

  const runSearch = debounce(async (q) => {
    if (q.trim().length < 2) {
      flatResults = [];
      closeList();
      return;
    }
    try {
      const url = `/api/search?q=${encodeURIComponent(q)}`;
      const data = coordinator
        ? await coordinator.fetch("global-search", url)
        : await apiFetch(url);
      if (data === undefined) return; // superseded by a newer keystroke
      flatResults = flattenGroupedResults(data);
      activeIndex = -1;
      renderResultsList(listboxEl, flatResults, activeIndex);
      if (flatResults.length > 0) openList();
      else openList(); // still open to show "no results" via ARIA live region elsewhere
    } catch (e) {
      flatResults = [];
      closeList();
    }
  }, debounceMs);

  inputEl.addEventListener("input", () => runSearch(inputEl.value));

  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (open) {
        closeList();
        event.preventDefault();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) openList();
      setActive(nextActiveIndex(activeIndex, flatResults.length, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) openList();
      setActive(nextActiveIndex(activeIndex, flatResults.length, -1));
    } else if (event.key === "Enter") {
      if (activeIndex >= 0 && flatResults[activeIndex]) {
        event.preventDefault();
        window.history.pushState({}, "", flatResults[activeIndex].url);
        window.dispatchEvent(new PopStateEvent("popstate"));
        closeList();
        inputEl.value = "";
      }
    }
  });

  document.addEventListener("click", (event) => {
    if (event.target !== inputEl && !listboxEl.contains(event.target)) closeList();
  });

  closeList();
}
