# Product

## Register

product

## Users

Draindeck Dashboard serves the operator or maintainer running Draindeck across a local portfolio of software repositories. They need to understand what the runtime observed, find issues that require intervention, inspect runs and executions, and verify evidence without reading JSONL files or confusing an inference with a fact.

The primary product environment is a desktop or tablet workstation. The initial operating envelope is approximately 20 registered repositories, 1,000 issues, 10,000 executions, and 100,000 or more evidence records. Mobile-specific workflows are not a v1 product target, but non-tabular content must still reflow to 320 CSS pixels so zoom and narrow-window use do not exclude users.

## Product Purpose

Draindeck Dashboard is the local operator surface for Draindeck. Its home screen fuses cross-repository health with current attention conditions; deeper workspaces provide repository, issue, run, execution, transcript, diff, and evidence inspection, plus configured-issue selection and run launch. It makes the runtime's durable record navigable while preserving a narrowly-scoped safety boundary: the Dashboard never opens, parses, or repairs a target's event log, mutates target Git state or source, or touches the runtime workspace lease itself. Two explicit, ADR-gated exceptions exist — writing a target's own `.draindeck/config.local.yaml` (ADR-29), and launching at most one `draindeck run` process per registered repository via a fixed argv vector (ADR-30) — beyond those, target repositories, logs, and artifacts remain unmodified.

Success means an operator can answer four questions quickly: What needs me now? What happened? What evidence supports that conclusion? Where can I inspect the exact related issue, run, execution, transcript, or diff? Every answer must distinguish observed facts from derived presentation and must remain useful under partial, malformed, legacy, or disconnected conditions.

## Brand Personality

Editorial, exacting, and calm.

The product should feel like a beautifully composed operations journal: confident enough for dense technical work, warm enough for sustained use, and restrained enough that evidence remains the protagonist. Copy is direct and factual. Status language never dramatizes or overclaims.

## Anti-references

- SaaS marketing landing pages, vanity hero sections, conversion copy, and decorative product claims.
- Generic admin templates made from repetitive floating cards and equal-weight KPI tiles.
- Neon cyberpunk dashboards, purple gradients, glassmorphism, gradient text, and glowing status chrome.
- Whole-portfolio force graphs used as spectacle rather than as a scoped explanatory tool.
- Interfaces that imply process liveness, cryptographic verification, exact progress, or causality the data does not establish.
- Mobile-first feature compromises that squeeze desktop data tables into unusable cards; v1 is desktop/tablet focused even though non-tabular accessibility reflow remains required down to 320 CSS pixels.

## Design Principles

1. **Triage before tour.** Open on cross-repository health and attention, never on marketing or decoration.
2. **Evidence before interpretation.** Lead with observed records, label derived facts, and never turn absence of evidence into a liveness claim.
3. **Density with orientation.** Support serious tables, linked details, filters, pagination, and stable URLs while preserving clear hierarchy and context.
4. **Local trust made explicit.** State and uphold the narrow, named exceptions to "target repositories, logs, and artifacts are not modified" (config writes, run launches) rather than an unqualified claim; describe Dashboard-owned SQLite writes precisely.
5. **Graceful degradation is a feature.** Loading, empty, stale, reconnecting, malformed, truncated, legacy, and inconsistent states receive first-class designs.

## Accessibility & Inclusion

Meet WCAG 2.2 AA. Every workflow must be keyboard operable, preserve visible and unobscured focus, expose semantic names and status updates, work at 200% zoom, reflow non-tabular content to 320 CSS pixels, avoid color-only meaning, honor reduced motion, and support system-aware plus manual light and dark themes. Tables need accessible headers and captions; charts need equivalent textual summaries and navigable data links. The designed product experience targets desktop and tablet viewports in v1; narrow-window reflow below 768 CSS pixels is an accessibility mode, not a separate mobile feature set.
