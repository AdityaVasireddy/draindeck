"""Configuration loader (doc 09 §3, canonical example in doc 08 §6).

Loaded once at startup, fully validated before any side effect, passed
as an immutable object. Two validation layers:

* structural — shape, enums, ranges; always runs (`load_config`).
* environment — repo path exists / is a git repo / branch exists /
  ANTHROPIC_API_KEY presence rules; runs via `validate_environment`,
  separable so unit tests and tooling can load config without a live
  target repo.
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigError(ValueError):
    pass


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationCfg(_Frozen):
    commands: list[str] = Field()
    timeout_seconds: int = Field(gt=0, default=600)
    # ADR-24 (doc 08 §5f): explicit no-validation acknowledgement. commands
    # may be empty ONLY when this is True -- enforced below by
    # _no_gate_requires_acknowledgement, not by Field(min_length=1), so the
    # two conditions can be checked together. Defaults False: every config
    # written before this field existed parses with acknowledged_no_gate
    # unset -> False -> its non-empty commands list (the only way it could
    # have loaded under the old min_length=1 rule) still validates.
    acknowledged_no_gate: bool = False
    # ADR-23 rule 3 (doc 08 §5d): extra vars merged into the VALIDATION child
    # env by Validator._run_once. ADR-18/ADR-22 hygiene governs the engine
    # child only — this is the validator child's equivalent, and it is not the
    # same mechanism. A value of None means UNSET the key in the child, not
    # "leave it inherited" and not "set it empty": empty != absent (a tool
    # testing `"VIRTUAL_ENV" in os.environ` sees "" as present), so an
    # additive-only overlay could not neutralize the vector behind the bug
    # this ADR addresses. Machine-specific names live HERE, in config —
    # src/ stays language-agnostic and never learns what these mean.
    env: dict[str, str | None] = Field(default_factory=dict)
    # Gap-2 hook (doc 08 Amendment, Session 35). Both fields below must be
    # set together to activate it; either left None (the default) leaves
    # existing configs' behavior byte-identical to before this field
    # existed. new_test_pattern is an fnmatch glob matched against paths
    # RepositoryAdapter.added_files() reports for an execution's base->end
    # diff. new_test_command_prefix is the SAME absolute-interpreter
    # convention ADR-23 rule 1 requires of commands -- deliberately NOT
    # inferred from commands (rule 1: "the runtime resolves nothing").
    # Each matched added file becomes its OWN single-file command
    # (f"{new_test_command_prefix} {path}") -- never a bare
    # directory/glob handed to pytest itself, so ADR-23 rule 2 ("never a
    # bare runner, directory, or glob relying on discovery") is preserved:
    # the pattern only decides WHICH explicit per-file commands get
    # constructed, it is never itself passed to the test runner.
    new_test_pattern: str | None = None
    new_test_command_prefix: str | None = None

    @field_validator("commands")
    @classmethod
    def _powershell_safe_commands(cls, value: list[str]) -> list[str]:
        if any(not command.strip() for command in value):
            raise ValueError("validation.commands entries must be non-empty")
        if any("$" in command for command in value):
            raise ValueError("validation.commands may not contain '$'; use a .ps1 file with -File")
        return value

    @model_validator(mode="after")
    def _no_gate_requires_acknowledgement(self) -> "ValidationCfg":
        # ADR-24: an empty commands list is invalid UNLESS the operator has
        # explicitly acknowledged running without a validation gate. Non-empty
        # commands are always valid regardless of acknowledged_no_gate --
        # ADR-24 deliberately does not enforce mutual exclusion (a stale
        # `true` alongside real commands is harmless; commands still run).
        if not self.commands and not self.acknowledged_no_gate:
            raise ValueError(
                "validation.commands is empty; set "
                "validation.acknowledged_no_gate: true to intentionally run "
                "without a validation gate, or supply at least one command"
            )
        return self


class ProjectCfg(_Frozen):
    name: str
    repository: str
    branch: str
    issues_file: str = "Issues.md"
    validation: ValidationCfg


class EngineCfg(_Frozen):
    provider: Literal["claude-headless"]  # ADR-08: sole engine in v1
    auth_mode: Literal["subscription", "api_key"]  # ADR-18
    model: str = "default"
    max_turns: int = Field(gt=0, default=30)
    timeout_seconds: int = Field(gt=0, default=1800)
    containment_confirmation_seconds: int = Field(gt=0, default=30)
    # ADR-22 (B layer): extra vars merged into the engine child env by
    # _hygienic_env(). Machine-specific names (e.g. HISTORIAN_SWEEP_ACTIVE)
    # live HERE, in config — src/ stays generic. The ADR-18 strip is applied
    # after the merge and always wins. Sunset condition in doc 08 §5c.
    child_env: dict[str, str] = Field(default_factory=dict)

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, v: str) -> str:
        # Doc 03 amendment: RunStarted.payload.engine.model is never null
        # or empty. An empty-but-present model here would silently produce
        # an invalid lifecycle event downstream.
        if not v:
            raise ValueError("engine.model must not be empty")
        return v


class QwenCfg(_Frozen):
    endpoint: str
    model: str

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("reviewer.qwen.model must not be empty")
        return v


# Known reviewer providers. A new provider is added here (and given a
# factory in main.py's _REVIEWER_FACTORIES) rather than by widening a
# Literal type — the two registries are the whole abstraction.
KNOWN_REVIEWER_PROVIDERS: frozenset[str] = frozenset({"qwen"})


class ReviewerCfg(_Frozen):
    provider: str
    qwen: Optional[QwenCfg] = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in KNOWN_REVIEWER_PROVIDERS:
            raise ValueError(
                f"reviewer.provider {v!r} is not a known provider "
                f"(known: {sorted(KNOWN_REVIEWER_PROVIDERS)})"
            )
        return v


class BudgetCfg(_Frozen):  # ADR-09
    max_attempts_per_issue: int = Field(gt=0)
    max_executions_per_run: int = Field(gt=0)
    proxy_pricing: Literal["api_list_rates"] = "api_list_rates"
    hard_stop_proxy_cost_per_run_usd: float = Field(gt=0)

    # mode="before": pydantic's lax int/float coercion silently turns a YAML
    # `true`/`false` into 1/0 before an "after" validator or Field(gt=0)
    # ever runs -- isinstance(True, int) is True (verified), so by the time
    # a normal validator sees the value, its bool-ness is already erased.
    # This must run before that coercion to catch it at all (doc 03
    # amendment: a JSON boolean is not an integer/number for budget fields).
    @field_validator("max_attempts_per_issue", "max_executions_per_run",
                     "hard_stop_proxy_cost_per_run_usd", mode="before")
    @classmethod
    def _reject_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("must be a number, not a boolean")
        return v

    @field_validator("hard_stop_proxy_cost_per_run_usd")
    @classmethod
    def _finite_cost(cls, v: float) -> float:
        # gt=0 alone already rejects NaN (`nan > 0` is False) and -Infinity
        # (`-inf > 0` is False) under IEEE 754 (verified) -- but not
        # +Infinity (`inf > 0` is True), which math.isfinite catches.
        if not math.isfinite(v):
            raise ValueError("must be finite (not NaN or Infinity)")
        return v


class ExperimentCfg(_Frozen):  # ADR-19 — do not edit after run begins
    sample_size: int = Field(gt=0)
    attempt1_success_min: float = Field(gt=0, le=1)
    cost_per_shipped_issue_max_usd: float = Field(gt=0)


class BillingCfg(_Frozen):  # checklist A1 record
    posture: str
    headless_split_status: str
    verified_on: str
    reverify_at: str


class EventLogCfg(_Frozen):
    # Target-repo-owned by default (resolve-item, 2026-08-18): a bare
    # relative path here is resolved against project.repository, never the
    # invocation CWD (see resolve_event_log_path below) -- ".draindeck/" is
    # the same target-repo-owned convention `draindeck init` already uses
    # for config.local.yaml (doc 16 §0c). An absolute path is always used
    # as-is and is unaffected by this default or its resolution rule.
    path: str = ".draindeck/state/events.jsonl"


class AttemptsCfg(_Frozen):
    ref_namespace: str = "refs/attempts"


class Config(_Frozen):
    project: ProjectCfg
    engine: EngineCfg
    reviewer: ReviewerCfg
    budget: BudgetCfg
    experiment: ExperimentCfg
    billing: BillingCfg
    event_log: EventLogCfg = EventLogCfg()
    attempts: AttemptsCfg = AttemptsCfg()

    @field_validator("reviewer")
    @classmethod
    def _reviewer_subsection(cls, v: ReviewerCfg) -> ReviewerCfg:
        if v.provider == "qwen" and v.qwen is None:
            raise ValueError("reviewer.provider=qwen requires reviewer.qwen")
        return v


def resolve_event_log_path(cfg: Config) -> Path:
    """The one place event_log.path becomes a filesystem path (doc 03's
    authoritative runtime state, and the artifacts/ dir derived from its
    parent). A relative path is resolved against project.repository, the
    target repo Config already anchors every other path to -- NEVER against
    Draindeck's invocation CWD, which previously made the default log
    shared/stale across unrelated target repos (a foreign log's startup
    replay corrupting a different target's recovery -- the incident this
    function exists to prevent). An absolute path (explicit operator
    override) is returned unchanged, preserving existing configuration that
    already pins a specific location."""
    p = Path(cfg.event_log.path)
    return p if p.is_absolute() else Path(cfg.project.repository) / p


def load_config(path: Path | str) -> Config:
    """Structural load. Raises ConfigError with a pointed message."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: top level must be a mapping")
    try:
        return Config.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise ConfigError(f"{p}: {e}") from e


def validate_environment(cfg: Config, *, env: Optional[dict] = None) -> list[str]:
    """Environment checks; returns a list of failures (empty = pass).

    ADR-18 env hygiene is validated here and *enforced* by the engine
    wrapper: subscription mode must not leak ANTHROPIC_API_KEY into the
    spawned engine; api_key mode requires it present.
    """
    env = os.environ if env is None else env
    problems: list[str] = []

    repo = Path(cfg.project.repository)
    if not repo.exists():
        problems.append(f"project.repository does not exist: {repo}")
    elif not (repo / ".git").exists():
        problems.append(f"project.repository is not a git repository: {repo}")
    else:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet",
             f"refs/heads/{cfg.project.branch}"],
            cwd=repo, capture_output=True,
        )
        if r.returncode != 0:
            problems.append(
                f"branch {cfg.project.branch!r} not found in {repo}"
            )

    if cfg.engine.auth_mode == "api_key" and not env.get("ANTHROPIC_API_KEY"):
        problems.append("engine.auth_mode=api_key but ANTHROPIC_API_KEY is not set")
    if cfg.engine.auth_mode == "subscription" and env.get("ANTHROPIC_API_KEY"):
        problems.append(
            "engine.auth_mode=subscription but ANTHROPIC_API_KEY is set — "
            "engine wrapper will strip it; unset it to avoid ambiguity (ADR-18)"
        )
    return problems
