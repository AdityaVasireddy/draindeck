"use strict";
// Shared metadata-only timeline list and bounded mini-topology renderers
// (docs/27 SS6.5-6.7, SS9.4). Timeline items are observed metadata
// records only -- never payload text. Topology is a small semantic
// SVG/DOM diagram with a text-list equivalent; it never invents
// causality beyond stored identifiers, and a truncated result links to
// the full filtered explorer rather than implying completeness.
import { el, timeElement } from "../dom.js";
import { formatAbsoluteTimestamp, formatRelativeTime } from "../format.js";

export function renderTimeline(listEl, items) {
  listEl.textContent = "";
  if (items.length === 0) {
    listEl.appendChild(el("li", { className: "empty-state" }, ["No timeline evidence observed yet."]));
    return;
  }
  const now = Date.now();
  for (const item of items) {
    const links = [];
    if (item.issueId) links.push(`issue ${item.issueId}`);
    if (item.executionId) links.push(`execution ${item.executionId}`);
    if (item.runId) links.push(`run ${item.runId}`);
    listEl.appendChild(el("li", null, [
      el("span", { className: "text-mono" }, [item.eventType || "(unknown type)"]),
      el("span", { className: "text-muted" }, [links.join(", ")]),
      timeElement(item.ts, formatAbsoluteTimestamp(item.ts), formatRelativeTime(item.ts, now)),
      el("span", { className: "text-label" }, [item.integrity]),
    ]));
  }
}

/** Renders both the semantic SVG diagram AND a text-list equivalent (the
    text list is the primary accessible representation; the SVG is
    decorative/supplementary and marked aria-hidden). */
export function renderTopology(containerEl, topology, repoId) {
  containerEl.textContent = "";
  if (topology.nodes.length === 0) {
    containerEl.appendChild(el("p", { className: "text-muted" }, ["No related entities observed yet."]));
    return;
  }

  const textList = el("ul", { className: "topology-text-list", "aria-label": "Related entities" });
  for (const edge of topology.edges) {
    const sourceUrl = entityUrl(repoId, edge.source);
    const targetUrl = entityUrl(repoId, edge.target);
    textList.appendChild(el("li", null, [
      el("a", { href: sourceUrl }, [`${edge.source.kind} ${edge.source.id}`]),
      ` ${edge.type.replace(/_/g, " ")} `,
      el("a", { href: targetUrl }, [`${edge.target.kind} ${edge.target.id}`]),
    ]));
  }
  containerEl.appendChild(textList);

  if (topology.truncated) {
    containerEl.appendChild(el("p", { className: "text-muted", role: "note" }, [
      `Showing ${topology.nodes.length} of the related entities (bounded at ` +
      `${topology.limits.maxNodes} nodes / ${topology.limits.maxEdges} edges). `,
    ]));
  }
}

/** Exported for testing (pure, no DOM) -- maps a topology node's kind to
    its detail-page URL segment. */
export function entityUrl(repoId, node) {
  const plural = { issue: "issues", run: "runs", execution: "executions", evidence: "evidence" }[node.kind];
  return `/repositories/${repoId}/${plural}/${node.id}`;
}
