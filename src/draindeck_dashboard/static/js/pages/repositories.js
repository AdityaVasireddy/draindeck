"use strict";
// Repository Registry and Add Repository (docs/27 SS6.2). Registry is a
// table, not a card grid. Unregister deletes only Dashboard-owned rows
// -- never the log/artifacts/repository on disk -- and requires
// confirmation.
import { ApiError, apiFetch } from "../api.js";
import { clear, el, statusChip, syncList } from "../dom.js";
import { availabilityLabel, offsetToPage, pageToOffset } from "../format.js";

export const PAGE_SIZE_OPTIONS = [25, 50, 100];
const _AVAILABILITY_TONE = { AVAILABLE: "ok", EMPTY: "muted", NOT_INITIALIZED: "warn", OFFLINE: "danger" };

/** Pure: parses the registry's shareable list state from a URLSearchParams-like
    object (docs/27 SS4: page/pageSize/sort/direction/named filters). */
export function parseRegistryQuery(searchParams) {
  const page = Number.parseInt(searchParams.get("page"), 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize"), 10);
  return {
    page: Number.isFinite(page) && page >= 1 ? page : 1,
    pageSize: PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : PAGE_SIZE_OPTIONS[0],
    q: searchParams.get("q") || "",
    availability: searchParams.get("availability") || "",
    hasAttention: searchParams.get("hasAttention") === "true",
    sort: searchParams.get("sort") || "name",
    direction: searchParams.get("direction") || "asc",
  };
}

export function registryQueryToUrl(query) {
  const params = new URLSearchParams();
  if (query.page > 1) params.set("page", String(query.page));
  if (query.pageSize !== PAGE_SIZE_OPTIONS[0]) params.set("pageSize", String(query.pageSize));
  if (query.q) params.set("q", query.q);
  if (query.availability) params.set("availability", query.availability);
  if (query.hasAttention) params.set("hasAttention", "true");
  if (query.sort !== "name") params.set("sort", query.sort);
  if (query.direction !== "asc") params.set("direction", query.direction);
  const qs = params.toString();
  return qs ? `/repositories?${qs}` : "/repositories";
}

function buildApiUrl(query) {
  const params = new URLSearchParams();
  params.set("limit", String(query.pageSize));
  params.set("offset", String(pageToOffset(query.page, query.pageSize)));
  if (query.q) params.set("q", query.q);
  if (query.availability) params.set("availability", query.availability);
  if (query.hasAttention) params.set("hasAttention", "true");
  params.set("sort", query.sort);
  params.set("direction", query.direction);
  return `/api/repository-summaries?${params.toString()}`;
}

function renderTable(tbody, items) {
  syncList(tbody, items, (r) => r.id, (rowEl, repo) => {
    clear(rowEl);
    const nameCell = el("th", { scope: "row" }, [
      el("a", { href: `/repositories/${repo.id}`, className: "row-title" }, [repo.displayName]),
    ]);
    const availCell = el("td", null,
      [statusChip(availabilityLabel(repo.availability), _AVAILABILITY_TONE[repo.availability] || "muted")]);
    const attnCell = el("td", null, [String(repo.attentionCount)]);
    const pathCell = el("td", { className: "text-mono" }, [repo.projectPath]);
    rowEl.append(nameCell, availCell, attnCell, pathCell);
  }, el("td", { colspan: "4" }, ["No repositories registered yet."]), "tr");
}

async function loadRegistry(root, query, ctx) {
  const tbody = root.querySelector("tbody");
  const statusEl = root.querySelector("[data-pagination-status]");
  try {
    const coordinator = ctx && ctx.coordinator;
    const data = coordinator
      ? await coordinator.fetch("repositories:list", buildApiUrl(query))
      : await apiFetch(buildApiUrl(query));
    if (data === undefined) return; // superseded
    renderTable(tbody, data.items);
    statusEl.textContent = `${data.total} repositor${data.total === 1 ? "y" : "ies"}`;
  } catch (err) {
    clear(tbody);
    tbody.appendChild(el("tr", null, [
      el("td", { colspan: "4", role: "alert" }, [`Could not load repositories: ${err.message}`]),
    ]));
  }
}

export async function render(root, params, ctx) {
  clear(root);
  const query = parseRegistryQuery(new URLSearchParams(window.location.search));

  root.appendChild(el("h1", { className: "text-display" }, ["Repositories"]));

  const searchForm = el("form", { role: "search", className: "registry-filters" }, [
    el("label", { className: "visually-hidden", for: "registry-search" }, ["Search repositories"]),
    el("input", { id: "registry-search", type: "search", name: "q", value: query.q,
                 placeholder: "Search repositories…" }),
    el("a", { href: "/repositories/new-target", className: "btn btn-primary" }, ["New target"]),
    el("a", { href: "/repositories/new", className: "btn btn-secondary" }, ["Register existing target"]),
  ]);
  root.appendChild(searchForm);

  const wrapper = el("div", { className: "ledger-table-wrapper" });
  const table = el("table", { className: "ledger-table" }, [
    el("caption", { className: "visually-hidden" }, ["Registered repositories"]),
    el("thead", null, [
      el("tr", null, [
        el("th", { scope: "col" }, ["Name"]),
        el("th", { scope: "col" }, ["Availability"]),
        el("th", { scope: "col" }, ["Attention"]),
        el("th", { scope: "col" }, ["Project path"]),
      ]),
    ]),
    el("tbody"),
  ]);
  wrapper.appendChild(table);
  root.appendChild(wrapper);

  const pagination = el("div", { className: "pagination" }, [
    el("p", { "data-pagination-status": "", className: "pagination-status" }, ["Loading…"]),
  ]);
  root.appendChild(pagination);

  await loadRegistry(root, query, ctx);

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const q = new FormData(searchForm).get("q") || "";
    const url = registryQueryToUrl({ ...query, q: String(q), page: 1 });
    // Same-page filter -- keep focus on the search field, not the main
    // landmark, so the user can keep typing/correcting their query.
    // render()'s synchronous rebuild replaces the input node itself, so
    // the old (focused) one must be explicitly replaced with its
    // successor rather than relying on preserveFocus alone.
    if (ctx && ctx.navigate) {
      ctx.navigate(url, { preserveFocus: true });
      const newInput = root.querySelector("#registry-search");
      if (newInput) {
        newInput.focus();
        newInput.setSelectionRange(newInput.value.length, newInput.value.length);
      }
    } else { window.history.pushState({}, "", url); window.dispatchEvent(new PopStateEvent("popstate")); }
  });
}

/** SSE-invalidation path (docs/27 SS9.3): re-fetches and syncList-updates
    only the table body/pagination status, reusing the shell render()
    already mounted -- never touches the search input or its focus/caret
    position. */
export async function refresh(root, params, ctx) {
  const query = parseRegistryQuery(new URLSearchParams(window.location.search));
  await loadRegistry(root, query, ctx);
}

/** Add Repository (docs/27 SS6.2): required absolute project path,
    optional absolute log path, typed validation inline and as a
    form-level alert, no browser Browse control. */
export async function renderAdd(root) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Add repository"]));

  const form = el("form", { className: "register-form" });
  const projectField = el("div", { className: "field" }, [
    el("label", { for: "add-project-path" }, ["Project path"]),
    el("input", { id: "add-project-path", name: "projectPath", required: true,
                 placeholder: "C:\\Projects\\StockPhotoAgent", autocomplete: "off" }),
  ]);
  const logField = el("div", { className: "field" }, [
    el("label", { for: "add-log-path" }, ["Log path (optional)"]),
    el("input", { id: "add-log-path", name: "logPath",
                 placeholder: "C:\\Projects\\StockPhotoAgent\\.draindeck\\state\\events.jsonl",
                 autocomplete: "off" }),
  ]);
  const alertEl = el("p", { role: "alert", className: "field-error-text" });
  const submitBtn = el("button", { type: "submit", className: "btn btn-primary" }, ["Add repository"]);

  form.append(projectField, logField, submitBtn, alertEl);
  root.appendChild(form);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    alertEl.textContent = "";
    const data = new FormData(form);
    const projectPath = String(data.get("projectPath") || "").trim();
    const logPath = String(data.get("logPath") || "").trim();
    try {
      const created = await apiFetch("/api/repositories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectPath, logPath: logPath || null }),
      });
      window.history.pushState({}, "", `/repositories/${created.id}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (err) {
      alertEl.textContent = err instanceof ApiError ? err.message : String(err);
    }
  });
}
