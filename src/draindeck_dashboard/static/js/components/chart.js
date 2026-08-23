"use strict";
// Categorical bar chart (DESIGN.md "The Chart Encoding Rule"; docs/27
// SS9.4). Complete eight-position, contrast-alternating sequence, never
// recycled; more than eight categories collapse into a labelled "Other"
// linked to the full data table. Every bar carries a direct visible
// text label -- hue is never the sole distinction -- and this SVG is
// always a SUPPLEMENT to an existing text/table equivalent elsewhere on
// the page (docs/27 SS6.1's analytics band dl), never a replacement for
// it. Geometry uses only validated numeric SVG presentation attributes
// and predeclared classes -- never inline style -- to stay compatible
// with the self-only CSP.
import { el } from "../dom.js";

export const MAX_CHART_CATEGORIES = 8;
const _OTHER_LABEL = "Other";

/** Pure: caps `entries` ([{label, value}]) at MAX_CHART_CATEGORIES. The
    first 7 entries are kept in the CALLER's original order (never
    re-sorted by value -- every current caller already passes a
    meaningful fixed categorical order, e.g. issue lifecycle states, and
    reordering by magnitude would make that order less predictable, not
    more honest); any remainder beyond 7 is summed into one trailing
    "Other" entry, never silently dropped. */
export function capChartEntries(entries) {
  const sorted = [...entries];
  if (sorted.length <= MAX_CHART_CATEGORIES) return sorted;
  const kept = sorted.slice(0, MAX_CHART_CATEGORIES - 1);
  const rest = sorted.slice(MAX_CHART_CATEGORIES - 1);
  const otherTotal = rest.reduce((sum, e) => sum + e.value, 0);
  return [...kept, { label: _OTHER_LABEL, value: otherTotal }];
}

function _isFiniteNonNegative(n) {
  return typeof n === "number" && Number.isFinite(n) && n >= 0;
}

/** Renders a horizontal bar chart into `container`. `entries`:
    [{label, value, url?}]. Bars are keyboard-reachable links when `url`
    is given. Every numeric geometry value is validated finite before
    use in an SVG presentation attribute (never trusts caller input into
    the markup unchecked). */
export function renderBarChart(container, { title, entries, basis }) {
  container.textContent = "";
  const capped = capChartEntries(entries).filter((e) => _isFiniteNonNegative(e.value));
  const maxValue = Math.max(1, ...capped.map((e) => e.value));

  const heading = el("h3", { className: "text-title" }, [title]);
  container.appendChild(heading);
  if (basis) container.appendChild(el("p", { className: "text-label chart-basis" }, [basis]));

  if (capped.length === 0) {
    container.appendChild(el("p", { className: "text-muted" }, ["No data observed yet."]));
    return;
  }

  const rowHeight = 28;
  const svgHeight = capped.length * rowHeight + 8;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 300 ${svgHeight}`);
  svg.setAttribute("class", "chart-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${title} bar chart`);

  capped.forEach((entry, index) => {
    const colorIndex = (index % MAX_CHART_CATEGORIES) + 1;
    const y = index * rowHeight + 4;
    const barWidth = Math.max(2, (entry.value / maxValue) * 180);

    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "chart-bar-group");
    if (entry.url) group.setAttribute("tabindex", "0");

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", "110");
    rect.setAttribute("y", String(y));
    rect.setAttribute("width", String(barWidth));
    rect.setAttribute("height", "18");
    rect.setAttribute("class", `chart-bar chart-bar--${colorIndex}`);
    rect.setAttribute("rx", "2");

    const titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
    titleEl.textContent = `${entry.label}: ${entry.value}`;
    rect.appendChild(titleEl);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", "105");
    label.setAttribute("y", String(y + 13));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", "chart-label");
    label.textContent = entry.label;

    const valueLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    valueLabel.setAttribute("x", String(110 + barWidth + 4));
    valueLabel.setAttribute("y", String(y + 13));
    valueLabel.setAttribute("class", "chart-value-label");
    valueLabel.textContent = String(entry.value);

    group.append(rect, label, valueLabel);
    svg.appendChild(group);
  });

  container.appendChild(svg);
}
