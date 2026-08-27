"use strict";
// About & Safety (docs/27 SS6.9): local-only, mutation-boundary,
// connection, database, and version facts. The safety/disclosure text is
// static and owned entirely by this module -- only host/port/database
// path/version are genuinely config- or build-dependent, fetched from
// `/api/about`.
import { apiFetch } from "../api.js";
import { clear, el } from "../dom.js";

export const MUTATION_BOUNDARY_TEXT =
  "Draindeck Dashboard does not modify registered repositories, event logs, transcripts, diffs, or artifacts. It writes its own local SQLite database for registration and indexed views.";

export const LOCAL_ONLY_TEXT =
  "This server binds only to 127.0.0.1 and rejects any request whose Host or Origin header is not loopback -- it is never reachable from another machine.";

export const CSP_TEXT =
  "Every response carries a self-only Content-Security-Policy and frame-ancestors 'none' -- no script, style, or frame from any other origin is ever loaded, and this page cannot be embedded in another page.";

export const CONNECTION_TEXT =
  "“Updates connected” in the top bar means this page is receiving a live server-sent-events stream of change notifications and re-fetches affected views automatically. “Reconnecting” means the stream dropped and the browser is retrying; data already on screen may be stale until it reconnects.";

export const THEME_TEXT =
  "Your light/dark theme choice is stored only in this browser's local storage -- it is never sent to the server and never shared across machines.";

export const NO_AUTH_TEXT =
  "There is no login, no user account, and no remote access support: anyone who can reach 127.0.0.1 on this machine can use this Dashboard.";

// Proxy cost, defined honestly (spec §5): a proxy, never an invoice, with the
// full exclusion list stated plainly.
export const PROXY_COST_DEFINITION_TEXT =
  "Proxy cost is the coding engine's own reported token usage priced at API list rates (basis ENGINE_REPORTED_API_LIST_RATE_PROXY). It is a proxy, not an invoice: it is not a bill, and missing cost is shown as unknown, never as $0.00.";

export const PROXY_COST_EXCLUSIONS_TEXT =
  "Excluded from proxy cost: reviewer-LLM cost, validation compute, orchestration cost (the Draindeck runtime's own coordinating compute -- the orchestrator loop, Git operations, recovery), subscription fees, and usage from crashed executions that never reported a terminal result. Proxy cost is also not shown on the Evidence, Search, or Attention screens.";

/** Pure: turns the `/api/about` response into an ordered facts list for
    display. */
export function buildAboutFacts(data) {
  return [
    { label: "Host", value: String(data.host) },
    { label: "Port", value: String(data.port) },
    { label: "Database", value: String(data.dbPath) },
    { label: "Version", value: String(data.version) },
  ];
}

export async function render(root, params, ctx) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["About & Safety"]));

  const section = el("section");
  section.append(
    el("p", null, [MUTATION_BOUNDARY_TEXT]),
    el("p", null, [LOCAL_ONLY_TEXT]),
    el("p", null, [CSP_TEXT]),
    el("p", null, [CONNECTION_TEXT]),
    el("p", null, [THEME_TEXT]),
    el("p", null, [NO_AUTH_TEXT]),
  );
  root.appendChild(section);

  const costSection = el("section", { "aria-labelledby": "about-cost-heading" }, [
    el("h2", { id: "about-cost-heading", className: "text-headline" }, ["Proxy cost"]),
    el("p", null, [PROXY_COST_DEFINITION_TEXT]),
    el("p", null, [PROXY_COST_EXCLUSIONS_TEXT]),
  ]);
  root.appendChild(costSection);

  const factsContainer = el("div");
  root.appendChild(factsContainer);

  try {
    const coordinator = ctx && ctx.coordinator;
    const url = "/api/about";
    const data = coordinator ? await coordinator.fetch("about:facts", url) : await apiFetch(url);
    if (data === undefined) return;
    const dl = el("dl", { className: "identity-block" });
    for (const fact of buildAboutFacts(data)) {
      dl.appendChild(el("dt", null, [fact.label]));
      dl.appendChild(el("dd", { className: "text-mono" }, [fact.value]));
    }
    factsContainer.appendChild(dl);
  } catch (err) {
    factsContainer.appendChild(el("p", { role: "alert" }, [`Could not load version/database facts: ${err.message}`]));
  }
}
