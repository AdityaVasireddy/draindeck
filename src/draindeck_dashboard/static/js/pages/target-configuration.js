"use strict";
// ADR-29 / spec/dashboard-target-configuration.md: New Target and Edit
// Configuration. The Dashboard never assembles or quotes YAML itself --
// /api/target-configurations/render (New Target) and the existing
// canonical config text (Edit Configuration) are the only sources of the
// rendered config text; every apply goes through the shared
// runtime.init.service via /api/target-configurations (POST/PATCH), the
// same guarantees the CLI gets.
import { ApiError, apiFetch } from "../api.js";
import { clear, el } from "../dom.js";

const BRANCH_OPERATION_TEXT = {
  CREATE: (branch) => `A new branch "${branch}" will be created at the target repository's current commit.`,
  CHECKOUT: (branch) => `The existing branch "${branch}" will be checked out. Its history is preserved -- ` +
    `it is never force-reset.`,
  UNKNOWN: (branch) => `The effect on branch "${branch}" could not be determined in advance.`,
};

function shortDigest(digest) {
  return digest ? digest.slice(0, 12) : "(none)";
}

function parseCommands(text) {
  return text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
}

/** Shared essential-settings fields: repository path (New only -- Edit's
    path is fixed to the registered repository and shown read-only),
    branch, validation commands / no-gate acknowledgement. */
function buildEssentialFields({ mode, initialProjectPath, initialBranch }) {
  const fields = el("div", { className: "target-config-essentials" });

  let projectPathInput = null;
  if (mode === "new") {
    const field = el("div", { className: "field" }, [
      el("label", { for: "tc-project-path" }, ["Repository path"]),
      el("input", { id: "tc-project-path", name: "projectPath", required: true,
                   value: initialProjectPath || "", autocomplete: "off",
                   placeholder: "C:\\Projects\\StockPhotoAgent" }),
    ]);
    projectPathInput = field.querySelector("input");
    fields.appendChild(field);
  } else {
    fields.appendChild(el("div", { className: "field" }, [
      el("label", { for: "tc-project-path-ro" }, ["Repository path"]),
      el("input", { id: "tc-project-path-ro", value: initialProjectPath || "", readonly: true, disabled: true }),
    ]));
  }

  // Edit mode has no branch field: the YAML editor below is the sole
  // source of truth there (see wireForm), so a separate branch input would
  // look editable while silently doing nothing -- a real defect a live
  // browser check caught. New Target still needs it to build a render
  // request before any YAML exists yet.
  let branchInput = null;
  if (mode === "new") {
    const branchField = el("div", { className: "field" }, [
      el("label", { for: "tc-branch" }, ["Work branch"]),
      el("input", { id: "tc-branch", name: "branch", required: true,
                   value: initialBranch || "agent-work", autocomplete: "off" }),
    ]);
    fields.appendChild(branchField);
    branchInput = branchField.querySelector("input");
  }

  return { fields, projectPathInput, branchInput };
}

/** Reads the branch name straight out of the exact YAML text just
    previewed/applied -- authoritative in both New and Edit mode, unlike a
    separate form field that Edit mode has no way to keep in sync with. */
function extractBranchName(yamlText) {
  const match = yamlText.match(/^\s*branch:\s*(.+?)\s*$/m);
  if (!match) return "(unknown)";
  let value = match[1].trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1);
  }
  return value;
}

/** New Target only: detected-defaults step over
    GET /api/target-configurations/detect, plus the validation-command
    textarea and the ADR-24 no-validation-gate acknowledgement. */
function buildValidationStep() {
  const wrap = el("div", { className: "target-config-validation" });
  const detectRow = el("div", { className: "dialog-actions", style: "justify-content: flex-start;" }, [
    el("button", { type: "button", id: "tc-detect-btn", className: "btn btn-secondary" }, ["Detect validation command"]),
  ]);
  const detectStatus = el("p", { id: "tc-detect-status", "aria-live": "polite", className: "field-hint" });
  const commandsField = el("div", { className: "field" }, [
    el("label", { for: "tc-commands" }, ["Validation commands (one per line)"]),
    el("textarea", { id: "tc-commands", name: "commands", rows: "4",
                    placeholder: "cargo test" }),
    el("p", { className: "field-hint" }, ["Run in the target repository before a change is accepted."]),
  ]);
  const noGateField = el("div", { className: "field field-checkbox" }, [
    el("input", { type: "checkbox", id: "tc-no-gate", name: "noGate" }),
    el("label", { for: "tc-no-gate" }, ["Proceed without any validation gate (not recommended)"]),
  ]);
  wrap.append(detectRow, detectStatus, commandsField, noGateField);
  return {
    wrap,
    detectBtn: detectRow.querySelector("#tc-detect-btn"),
    detectStatus,
    commandsInput: commandsField.querySelector("textarea"),
    noGateInput: noGateField.querySelector("input"),
  };
}

/** Advanced settings: the exact rendered YAML, always editable directly --
    every schema field (engine/reviewer/budget/event-log/billing/
    experiment) is reachable this way even though only branch/validation
    have dedicated essential-settings fields. Editing this textarea by hand
    overrides the essential fields for the NEXT preview. */
function buildAdvancedSection({ openByDefault }) {
  const details = el("details", { className: "advanced-settings" });
  if (openByDefault) details.setAttribute("open", "");
  const summary = el("summary", null, ["Advanced: exact configuration"]);
  const field = el("div", { className: "field" }, [
    el("label", { for: "tc-yaml" }, ["Generated config.local.yaml"]),
    el("textarea", { id: "tc-yaml", className: "yaml-editor", rows: "18", spellcheck: "false" }),
    el("p", { className: "field-hint" },
      ["Edit engine, reviewer, budget, event-log, attempts, billing, or experiment settings here directly."]),
  ]);
  const resetBtn = el("button", { type: "button", id: "tc-reset-yaml", className: "btn-ghost" },
    ["Reset to generated defaults"]);
  details.append(summary, field, resetBtn);
  return { details, yamlInput: field.querySelector("textarea"), resetBtn };
}

function buildPreviewPanel() {
  const panel = el("div", { className: "target-config-preview", hidden: true });
  const branchWarning = el("div", { className: "banner banner--warning", role: "status", hidden: true });
  const digestLine = el("p", { className: "field-hint" });
  const confirmField = el("div", { className: "field field-checkbox", hidden: true }, [
    el("input", { type: "checkbox", id: "tc-confirm-branch" }),
    el("label", { for: "tc-confirm-branch" }, ["I understand and confirm this branch effect."]),
  ]);
  panel.append(branchWarning, digestLine, confirmField);
  return {
    panel, branchWarning, digestLine, confirmField,
    confirmInput: confirmField.querySelector("input"),
  };
}

function renderForm(root, { mode, heading, initialProjectPath, initialBranch, initialYaml, submitLabel }) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, [heading]));

  const form = el("form", { className: "target-config-form" });
  const { fields: essentials, projectPathInput, branchInput } = buildEssentialFields({
    mode, initialProjectPath, initialBranch,
  });
  const validation = mode === "new" ? buildValidationStep() : null;
  const advanced = buildAdvancedSection({ openByDefault: mode === "edit" });
  if (initialYaml) advanced.yamlInput.value = initialYaml;
  const preview = buildPreviewPanel();
  const formError = el("p", { role: "alert", className: "field-error-text" });

  const actions = el("div", { className: "dialog-actions" }, [
    el("button", { type: "button", id: "tc-preview-btn", className: "btn btn-secondary" }, ["Preview"]),
    el("button", { type: "submit", id: "tc-apply-btn", className: "btn btn-primary", disabled: true },
      [submitLabel]),
  ]);

  form.appendChild(essentials);
  if (validation) form.appendChild(validation.wrap);
  form.appendChild(advanced.details);
  form.appendChild(preview.panel);
  form.appendChild(formError);
  form.appendChild(actions);
  root.appendChild(form);

  return {
    form, projectPathInput, branchInput, validation, advanced, preview, formError,
    previewBtn: actions.querySelector("#tc-preview-btn"),
    applyBtn: actions.querySelector("#tc-apply-btn"),
  };
}

function currentProjectPath(handles, fixedProjectPath) {
  return fixedProjectPath || (handles.projectPathInput ? handles.projectPathInput.value.trim() : "");
}

/** Wires the shared preview/apply behavior. `fixedProjectPath` is set only
    in Edit mode (the registered repository's path, never editable here).
    `onApplied(result)` navigates away on success. */
function wireForm(handles, { fixedProjectPath, applyFn, onApplied }) {
  const { form, branchInput, validation, advanced, preview, formError, previewBtn, applyBtn } = handles;
  let lastPreview = null; // { renderedYaml, currentConfigDigest, proposedConfigDigest, branchOperation, branchConfirmationRequired }
  let yamlManuallyEdited = false;
  let commandsAutoFilled = false;

  advanced.yamlInput.addEventListener("input", () => { yamlManuallyEdited = true; });

  if (validation) {
    validation.commandsInput.addEventListener("input", () => { commandsAutoFilled = false; });
    validation.noGateInput.addEventListener("change", () => {
      validation.commandsInput.disabled = validation.noGateInput.checked;
    });
    validation.detectBtn.addEventListener("click", async () => {
      const projectPath = currentProjectPath(handles, fixedProjectPath);
      if (!projectPath) { validation.detectStatus.textContent = "Enter a repository path first."; return; }
      validation.detectStatus.textContent = "Detecting…";
      try {
        const result = await apiFetch(
          `/api/target-configurations/detect?projectPath=${encodeURIComponent(projectPath)}`);
        if (result.chosenStack) {
          validation.detectStatus.textContent = `Detected: ${result.chosenStack}.`;
          if (!commandsAutoFilled && validation.commandsInput.value.trim() === "" && result.proposedCommands.length) {
            validation.commandsInput.value = result.proposedCommands.join("\n");
            commandsAutoFilled = true;
          }
        } else {
          validation.detectStatus.textContent = "No recognized stack marker found.";
        }
      } catch (err) {
        validation.detectStatus.textContent = err instanceof ApiError ? err.message : String(err);
      }
    });
  }

  function resetApplyState() {
    lastPreview = null;
    applyBtn.disabled = true;
    preview.panel.hidden = true;
    preview.branchWarning.hidden = true;
    preview.confirmField.hidden = true;
    preview.confirmInput.checked = false;
  }

  advanced.resetBtn.addEventListener("click", () => {
    yamlManuallyEdited = false;
    resetApplyState();
  });

  async function runPreview() {
    formError.textContent = "";
    const projectPath = currentProjectPath(handles, fixedProjectPath);
    if (!projectPath) { formError.textContent = "Repository path is required."; return; }
    try {
      let renderedYaml;
      if (validation && !yamlManuallyEdited) {
        const commands = validation.noGateInput.checked ? [] : parseCommands(validation.commandsInput.value);
        if (commands.length === 0 && !validation.noGateInput.checked) {
          formError.textContent = "Enter at least one validation command, or acknowledge no validation gate.";
          return;
        }
        const rendered = await apiFetch("/api/target-configurations/render", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectPath, branch: branchInput.value.trim(), commands }),
        });
        renderedYaml = rendered.renderedYaml;
        advanced.yamlInput.value = renderedYaml;
      } else {
        renderedYaml = advanced.yamlInput.value;
      }
      const previewed = await apiFetch("/api/target-configurations/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectPath, renderedYaml }),
      });
      lastPreview = { ...previewed, renderedYaml };
      preview.panel.hidden = false;
      preview.digestLine.textContent =
        `Current: ${shortDigest(previewed.currentConfigDigest)} → proposed: ${shortDigest(previewed.proposedConfigDigest)}`;
      if (previewed.branchOperation !== "NONE") {
        const textFn = BRANCH_OPERATION_TEXT[previewed.branchOperation] || BRANCH_OPERATION_TEXT.UNKNOWN;
        preview.branchWarning.textContent = textFn(extractBranchName(renderedYaml));
        preview.branchWarning.hidden = false;
      } else {
        preview.branchWarning.hidden = true;
      }
      preview.confirmField.hidden = !previewed.branchConfirmationRequired;
      preview.confirmInput.checked = !previewed.branchConfirmationRequired;
      applyBtn.disabled = previewed.branchConfirmationRequired;
      if (previewed.branchConfirmationRequired) {
        preview.confirmInput.addEventListener("change", () => {
          applyBtn.disabled = !preview.confirmInput.checked;
        }, { once: true });
      } else {
        applyBtn.disabled = false;
      }
    } catch (err) {
      resetApplyState();
      formError.textContent = err instanceof ApiError ? err.message : String(err);
    }
  }

  previewBtn.addEventListener("click", runPreview);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!lastPreview) { formError.textContent = "Preview the configuration before applying."; return; }
    formError.textContent = "";
    applyBtn.disabled = true;
    try {
      const result = await applyFn({
        projectPath: currentProjectPath(handles, fixedProjectPath),
        renderedYaml: lastPreview.renderedYaml,
        expectedConfigDigest: lastPreview.currentConfigDigest,
        branchChangeConfirmed: true,
      });
      onApplied(result);
    } catch (err) {
      applyBtn.disabled = false;
      if (err instanceof ApiError && err.code === "CONFIG_REVISION_CONFLICT") {
        formError.textContent = "This configuration changed since you last previewed it. Preview again to see the latest version before applying.";
        resetApplyState();
      } else {
        formError.textContent = err instanceof ApiError ? err.message : String(err);
      }
    }
  });
}

export async function renderNew(root, params, ctx) {
  const handles = renderForm(root, {
    mode: "new", heading: "New target",
    initialProjectPath: "", initialBranch: "agent-work", initialYaml: "",
    submitLabel: "Create target",
  });
  wireForm(handles, {
    fixedProjectPath: null,
    applyFn: (body) => apiFetch("/api/target-configurations", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
    onApplied: (result) => {
      const url = `/repositories/${result.registration.id}`;
      if (ctx && ctx.navigate) ctx.navigate(url);
      else { window.history.pushState({}, "", url); window.dispatchEvent(new PopStateEvent("popstate")); }
    },
  });
}

export async function renderEdit(root, params, ctx) {
  clear(root);
  root.appendChild(el("h1", { className: "text-display" }, ["Edit configuration"]));
  root.appendChild(el("p", { className: "text-muted" }, ["Loading current configuration…"]));

  const repoId = params.repoId;
  let registration;
  let configuration;
  try {
    registration = await apiFetch(`/api/repositories/${repoId}`);
    configuration = await apiFetch(`/api/repositories/${repoId}/configuration`);
  } catch (err) {
    clear(root);
    root.appendChild(el("h1", { className: "text-display" }, ["Edit configuration"]));
    if (err instanceof ApiError && err.status === 404) {
      root.appendChild(el("div", { className: "state-panel" }, [
        el("p", { className: "state-panel-title" }, ["No configuration found for this target yet."]),
        el("a", { href: "/repositories/new-target", className: "btn-ghost" }, ["Configure a new target"]),
      ]));
    } else {
      root.appendChild(el("p", { role: "alert", className: "field-error-text" },
        [err instanceof ApiError ? err.message : String(err)]));
    }
    return;
  }

  const handles = renderForm(root, {
    mode: "edit", heading: `Edit configuration — ${registration.projectPath}`,
    initialProjectPath: registration.projectPath, initialBranch: "",
    initialYaml: configuration.renderedYaml,
    submitLabel: "Save changes",
  });
  wireForm(handles, {
    fixedProjectPath: registration.projectPath,
    applyFn: (body) => apiFetch(`/api/repositories/${repoId}/configuration`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
    onApplied: () => {
      const url = `/repositories/${repoId}`;
      if (ctx && ctx.navigate) ctx.navigate(url);
      else { window.history.pushState({}, "", url); window.dispatchEvent(new PopStateEvent("popstate")); }
    },
  });
}
