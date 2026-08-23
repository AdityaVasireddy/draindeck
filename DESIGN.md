---
name: Draindeck Dashboard
description: An editorial operations journal for trustworthy local runtime evidence.
colors:
  forest-rail: "#153C31"
  forest-deep: "#0B2E25"
  paper-canvas: "#F6F1E8"
  paper-surface: "#FCF9F3"
  ink-primary: "#23332E"
  ink-muted: "#52645E"
  rule-light: "#CFC7B8"
  field-border-light: "#81796C"
  sage-action: "#386B46"
  sage-wash: "#E2EBDF"
  bronze-attention: "#7A5B2E"
  bronze-wash: "#F1E5CD"
  clay-danger: "#9B432E"
  clay-wash: "#F5DDD6"
  focus-teal: "#006E75"
  focus-on-dark: "#6EDAE0"
  night-canvas: "#14241E"
  night-surface: "#1D3028"
  night-ink: "#F5EFE6"
  night-muted: "#B8C9C0"
  night-rule: "#42554B"
  field-border-dark: "#82998D"
  night-sage: "#A6D6B0"
  night-bronze: "#F2C57C"
  night-clay: "#FFB4A5"
  chart-light-1: "#153C31"
  chart-light-2: "#007F87"
  chart-light-3: "#6B2F24"
  chart-light-4: "#5F7F36"
  chart-light-5: "#3D4972"
  chart-light-6: "#8A6A2F"
  chart-light-7: "#65405E"
  chart-light-8: "#52645E"
  chart-dark-1: "#A6D6B0"
  chart-dark-2: "#9D71A1"
  chart-dark-3: "#6EDAE0"
  chart-dark-4: "#C36E5B"
  chart-dark-5: "#F2C57C"
  chart-dark-6: "#6888C9"
  chart-dark-7: "#FFB4A5"
  chart-dark-8: "#7D8A3F"
typography:
  display:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "clamp(2rem, 3vw, 3.25rem)"
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "clamp(1.5rem, 2vw, 2rem)"
    fontWeight: 400
    lineHeight: 1.2
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0.055em"
  mono:
    fontFamily: "Cascadia Mono, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  control-sm: "4px"
  surface-md: "8px"
  surface-lg: "12px"
  pill: "999px"
spacing:
  xxs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.forest-rail}"
    textColor: "{colors.paper-surface}"
    typography: "{typography.title}"
    rounded: "{rounded.control-sm}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.forest-rail}"
    typography: "{typography.title}"
    rounded: "{rounded.control-sm}"
    padding: "9px 15px"
  input-search:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.ink-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.control-sm}"
    padding: "10px 12px"
  chip-attention:
    backgroundColor: "{colors.bronze-wash}"
    textColor: "{colors.bronze-attention}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "4px 8px"
  table-surface:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.surface-md}"
    padding: "0"
---

# Design System: Draindeck Dashboard

## Overview

**Creative North Star: "The Operator's Field Journal"**

Draindeck is a composed editorial workspace wrapped around durable runtime evidence. A deep forest rail anchors the application like a clothbound spine; warm paper surfaces hold dense, aligned records; sparing sage, bronze, and clay annotations behave like deliberate editorial marks. The interface is visually distinctive without competing with the facts.

The system balances the identity of Direction A, the density of Direction B, scoped topology from Direction C, and the resilient navigation and state language of Direction D. It rejects SaaS marketing landing pages, generic admin templates, neon cyberpunk dashboards, purple gradients, glassmorphism, gradient text, glowing status chrome, and force graphs used as spectacle. Desktop and tablet are first-class; density is reduced through progressive disclosure and reflow, never by hiding essential meaning behind hover.

**Key Characteristics:**

- Warm editorial shell with a deep forest application spine.
- Dense, aligned tables for registries and evidence; cards only for real grouping.
- Honest labels separating observed facts, derived summaries, and unavailable data.
- Restrained topology and charts that always link back to inspectable records.
- Quiet motion, crisp unobscured focus, and comprehensive non-ideal states.

## Colors

The palette combines archival paper, evergreen binding cloth, graphite ink, and three accessible annotation colors. Text pairs meet WCAG AA; dedicated field-border and theme-specific focus tokens meet the 3:1 non-text contrast threshold on their intended surfaces.

### Primary

- **Binding Forest** (`#153C31`): persistent rail, primary actions, selected navigation, and the strongest structural anchor.
- **Deep Binding Forest** (`#0B2E25`): pressed states and dark structural accents; never used as a decorative gradient.
- **Paper Canvas** (`#F6F1E8`): application workspace background.
- **Fresh Paper Surface** (`#FCF9F3`): tables, drawers, dialogs, and elevated working surfaces.

### Secondary

- **Editorial Sage** (`#386B46`) and **Sage Wash** (`#E2EBDF`): available, connected, accepted, and successful observations.
- **Margin Bronze** (`#7A5B2E`) and **Bronze Wash** (`#F1E5CD`): attention, reduced confidence, unknown types, pending reconciliation, and no-controlled-finish observations.
- **Correction Clay** (`#9B432E`) and **Clay Wash** (`#F5DDD6`): corrupt, oversized, offline, destructive, and failed conditions.
- **Proofreader Teal** (`#006E75`): visible keyboard focus and current inline navigation where forest would not stand apart.
- **Focus on Dark** (`#6EDAE0`): focus indicator on Binding Forest, Night Canvas, and Night Surface in either theme. Focus selection is surface-aware, not theme-only.

### Neutral

- **Graphite Ink** (`#23332E`): primary light-theme text.
- **Pencil Ink** (`#52645E`): secondary light-theme text; do not place lighter small text on paper.
- **Ledger Rule** (`#CFC7B8`): borders, dividers, row rules, and graph axes.
- **Field Border Light** (`#81796C`): interactive control boundary on light paper; Ledger Rule is too quiet to serve as the only field boundary.
- **Night Canvas** (`#14241E`) and **Night Surface** (`#1D3028`): dark-theme ground and surface.
- **Night Paper** (`#F5EFE6`) and **Night Pencil** (`#B8C9C0`): dark-theme primary and secondary text.
- **Night Rule** (`#42554B`): dark-theme borders and separators.
- **Field Border Dark** (`#82998D`): interactive control boundary on Night Canvas/Night Surface.
- **Night Sage** (`#A6D6B0`), **Night Bronze** (`#F2C57C`), and **Night Clay** (`#FFB4A5`): accessible dark-theme status foregrounds.

**The Annotation Rule.** Sage, bronze, and clay communicate status only when paired with text and an icon or shape; color and fill style never carry meaning alone.

**The Ten-Percent Rule.** Annotation colors occupy no more than roughly ten percent of a screen. Paper and forest establish identity; evidence remains visually dominant.

**The Chart Encoding Rule.** Categorical charts use a complete eight-position, contrast-alternating sequence. Light: `#153C31`, `#007F87`, `#6B2F24`, `#5F7F36`, `#3D4972`, `#8A6A2F`, `#65405E`, `#52645E`. Dark: `#A6D6B0`, `#9D71A1`, `#6EDAE0`, `#C36E5B`, `#F2C57C`, `#6888C9`, `#FFB4A5`, `#7D8A3F`. Every entry clears 3:1 against its intended canvas, and alternating luminance improves grayscale separation. Every segment also has a direct label, symbol or pattern, and text/table equivalent; hue is never the sole distinction. More than eight categories collapse into “Other” with a linked data table rather than recycling color.

## Typography

**Display Font:** Georgia (with Times New Roman and serif fallbacks)<br>
**Body Font:** system UI (with Segoe UI and sans-serif fallbacks)<br>
**Label/Mono Font:** Cascadia Mono (with Consolas and monospace fallbacks)

**Character:** Georgia supplies the field-journal identity only at page and major section scale. The system stack keeps dense operational reading crisp; mono is reserved for identifiers, hashes, paths, cursors, event types, and diff/transcript content. No network font is required.

### Hierarchy

- **Display** (400, `clamp(2rem, 3vw, 3.25rem)`, 1.08): one page title or high-level empty-state statement.
- **Headline** (400, `clamp(1.5rem, 2vw, 2rem)`, 1.2): section and detail-page headings.
- **Title** (650, `1rem`, 1.35): table group titles, drawer sections, primary controls.
- **Body** (400, `0.9375rem`, 1.55): descriptions, data values, and UI copy; prose columns stop near 72 characters.
- **Label** (700, `0.75rem`, `0.055em`, uppercase only for short labels): column labels, eyebrow text, and compact state descriptors.
- **Mono** (400, `0.8125rem`, 1.5): machine identifiers and source-like content; wrap long tokens at safe boundaries and provide copy actions.

**The One-Serif-Level Rule.** Never stack multiple decorative serif tiers inside a dense workspace; Georgia names the page or major section, while operational content remains sans-serif or mono.

## Elevation

The system is flat by default and creates depth through tonal layering, borders, and sticky-plane separation. Shadows are structural responses for menus, dialogs, drawers, and sticky headers—not a decoration applied to every row or card. Paper texture, if implemented, must be CSS-only, extremely subtle, disabled in forced-colors, and never reduce text contrast.

### Shadow Vocabulary

- **Sticky Plane** (`0 1px 0 rgba(11, 46, 37, 0.12)`): separates sticky headers or toolbars from scrolling evidence.
- **Floating Menu** (`0 8px 24px rgba(11, 46, 37, 0.14)`): menus, popovers, and typeahead results only.
- **Dialog / Drawer** (`0 18px 50px rgba(11, 46, 37, 0.22)`): modal confirmation and temporary overlay planes.

**The Flat-by-Default Rule.** Entity rows, metric summaries, and ordinary sections never receive individual drop shadows; use a one-pixel ledger rule and spacing instead.

## Components

Components feel tactile and precise: squared editorial controls, restrained rounding, visible borders, and state changes that do not move surrounding content.

### Buttons

- **Shape:** compact rectangle (`4px` radius), minimum `44px` target height where space allows.
- **Primary:** Binding Forest background, Fresh Paper text, `10px 16px` padding; reserved for the current screen's main action.
- **Hover / Focus:** tonal darkening without layout movement; `2px` Proofreader Teal on light paper and `2px` Focus on Dark on forest/night surfaces, each with `2px` offset. Sticky planes use `scroll-margin`/`scroll-padding` so focus is not obscured. Active state may translate by at most `1px` unless reduced motion is enabled.
- **Secondary / Ghost / Destructive:** bordered paper secondary; underlined text ghost for table actions; Correction Clay destructive action only inside a confirmation flow.

### Chips

- **Style:** compact pill for state text plus icon; use wash background and accessible foreground. Base availability, integrity, inconsistency, and attention remain separate chips when they are separate facts.
- **State:** selected filters use Binding Forest with Fresh Paper text; unselected filters use transparent paper with Ledger Rule border. Never encode ambiguity through outline versus solid alone.

### Cards / Containers

- **Corner Style:** `8px` for table and grouped content surfaces; `12px` only for prominent empty states, dialogs, or overview figures.
- **Background:** Fresh Paper on Paper Canvas; Night Surface on Night Canvas.
- **Shadow Strategy:** flat at rest; reference the structural shadow vocabulary for overlays only.
- **Border:** `1px` Ledger Rule or Night Rule.
- **Internal Padding:** `16px` for dense surfaces, `24px` for page-level sections, and `32px` only for prominent empty states.

### Inputs / Fields

- **Style:** paper surface, `1px` Field Border Light (Field Border Dark in dark theme), `4px` radius, `10px 12px` padding, explicit persistent label outside the field. Ledger Rule remains a divider only.
- **Focus:** `2px` Proofreader Teal on light paper or Focus on Dark on night surfaces plus a forest boundary shift; never remove the native semantic focus sequence.
- **Error / Disabled:** Correction Clay text and border with explicit error copy; disabled state keeps readable contrast and explains why when context is not obvious.

### Navigation

- The `240px` forest rail holds the wordmark and eight stable destinations. Active items use a paper-tinted block, icon, and text; an explicit expand control is available in collapsed tablet mode.
- The top utility bar contains simple global search, update-stream status, and theme control. Breadcrumbs orient all detail pages.
- At 768–1023px the rail collapses to `72px`; every destination retains a short visible label beneath/beside its icon plus an accessible name, so no tooltip is load-bearing. An explicit expand control restores full labels. Below 768px, a compact top navigation/disclosure and single-column non-tabular flow satisfy 320px accessibility reflow; this is not a separate mobile feature set and no mobile bottom navigation is part of v1.
- Any supplementary custom tooltip used elsewhere must satisfy WCAG 1.4.13: dismissible with Escape without moving focus, hoverable without disappearing, and persistent until hover/focus ends or the user dismisses it. Never use `title` or a tooltip as the only visible name/instruction.

### Ledger Table

Use semantic `<table>` markup for aligned entity comparisons. Headers may be sticky, sortable controls include visible direction text for assistive technology, row titles are ordinary links, bulk row clicks are optional enhancements only, and pagination remains outside the scrolling table. On narrow tablet layouts, preserve key columns and expose the remainder through an explicit row detail expander rather than stacking every cell into a card.

### Attention Row

Attention combines severity icon and label, exact condition, repository link, first-detected timestamp, current/resolved status, and a direct route to the relevant entity or repository health view. Critical conditions are never dismissible; resolved history may be filtered but remains evidence-derived.

### Mini Topology

The scoped issue/run topology is a small semantic SVG or DOM diagram showing observed relationships such as issue → executions → evidence. Every node is keyboard reachable, has a text-list equivalent, and links to its detail page. It is not a whole-portfolio force graph and never invents causality beyond stored identifiers.

### Charts

Charts use SVG, real aggregate values, labelled axes, the Chart Encoding Rule's fixed categorical order, keyboard-accessible data points, and an adjacent textual summary or data table. Geometry uses external classes or validated SVG presentation attributes—never inline `style`—to remain compatible with the self-only CSP. They are navigation aids into filtered records, not decorative KPI art. Reduced motion disables animated interpolation.

## Do's and Don'ts

### Do:

- **Do** open on fused cross-repository health and attention so the product starts with triage, not a tour.
- **Do** use Binding Forest (`#153C31`) for the application spine and warm Paper Canvas (`#F6F1E8`) for the workspace.
- **Do** use aligned tables, one-pixel ledger rules, and `8px` surfaces for dense entity comparison.
- **Do** label observed facts and derived summaries explicitly, including the exact phrase “no controlled finish observed.”
- **Do** pair every status/chart color with text and an icon, symbol, pattern, or shape; use dedicated field-border/focus tokens, preserve visible unobscured focus, and honor reduced motion and forced colors.
- **Do** design loading, empty, filtered-empty, API-error, reconnecting, stale-lease, malformed, oversized, corrupt, inconsistent, legacy, and truncated-artifact states alongside ideal data.
- **Do** preserve stable URLs, meaningful links, pagination, search context, and keyboard focus during incremental SSE updates.

### Don't:

- **Don't** build a SaaS marketing landing page, vanity hero section, conversion funnel, or decorative product-claim screen.
- **Don't** use generic admin templates made from repetitive floating cards or equal-weight KPI tiles.
- **Don't** use neon cyberpunk dashboards, purple gradients, glassmorphism, gradient text, or glowing status chrome.
- **Don't** use a whole-portfolio force graph as spectacle; topology is scoped to one issue or run and backed by observed identifiers.
- **Don't** imply process liveness, cryptographic verification, exact budget progress, precise causality, or any fact the Dashboard contracts do not expose.
- **Don't** squeeze desktop tables into mobile-style cards; v1 is desktop/tablet focused, while non-tabular content still reflows accessibly to `320px`.
- **Don't** apply `20–30px` radii, shadows to every row, heavy paper texture, ornamental asymmetry, hover-only information, color-only meaning, or motion that survives `prefers-reduced-motion: reduce`.
