"use strict";
// A minimal accessible modal (docs/27 dialog/drawer pattern, .dialog-backdrop
// + .dialog in components.css): role="dialog", aria-modal, a Tab/Shift+Tab
// focus trap, Escape to close, and focus RETURNED to whatever triggered the
// dialog on close (never left on a now-removed node). No animation is
// required to satisfy prefers-reduced-motion -- this dialog never animates.
import { el } from "../dom.js";

/** Opens a modal built from `titleText` + `bodyNodes`, with `actions` (an
    array of {label, className, onClick, autofocus?} button specs) rendered
    in a trailing .dialog-actions row. Returns {close(), dialogEl}. */
export function openDialog({ titleText, bodyNodes, actions, labelledById }) {
  const previouslyFocused = document.activeElement;
  const titleId = labelledById || `dialog-title-${Math.random().toString(36).slice(2)}`;

  const actionButtons = (actions || []).map((spec) =>
    el("button", {
      type: "button",
      className: spec.className || "btn-ghost",
    }, [spec.label]));

  const dialogBody = el("div", { className: "dialog", role: "dialog", "aria-modal": "true",
                                 "aria-labelledby": titleId }, [
    el("h2", { id: titleId, className: "text-headline" }, [titleText]),
    ...(bodyNodes || []),
    el("div", { className: "dialog-actions" }, actionButtons),
  ]);
  const backdrop = el("div", { className: "dialog-backdrop" }, [dialogBody]);

  actionButtons.forEach((btn, i) => {
    btn.addEventListener("click", () => {
      const spec = actions[i];
      if (spec.onClick) spec.onClick();
    });
  });

  function focusableElements() {
    return Array.from(dialogBody.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )).filter((node) => !node.disabled && node.offsetParent !== null);
  }

  function onKeydown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements();
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function close() {
    document.removeEventListener("keydown", onKeydown, true);
    backdrop.remove();
    if (previouslyFocused && typeof previouslyFocused.focus === "function") {
      previouslyFocused.focus();
    }
  }

  document.addEventListener("keydown", onKeydown, true);
  document.body.appendChild(backdrop);
  const initial = focusableElements();
  const autofocusTarget = actions && actions.findIndex((a) => a.autofocus);
  if (autofocusTarget >= 0 && actionButtons[autofocusTarget]) actionButtons[autofocusTarget].focus();
  else if (initial.length > 0) initial[0].focus();

  return { close, dialogEl: dialogBody };
}
