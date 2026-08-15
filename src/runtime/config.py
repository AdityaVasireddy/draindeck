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

import os
import subprocess
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigError(ValueError):
    pass


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationCfg(_Frozen):
    commands: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(gt=0, default=600)
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


class QwenCfg(_Frozen):
    endpoint: str
    model: str


class ClaudeReviewerCfg(_Frozen):
    auth_mode: Literal["subscription", "api_key"] = "subscription"


class ReviewerCfg(_Frozen):
    provider: Literal["qwen", "claude"]  # ADR-05
    qwen: Optional[QwenCfg] = None
    claude: Optional[ClaudeReviewerCfg] = None


class BudgetCfg(_Frozen):  # ADR-09
    max_attempts_per_issue: int = Field(gt=0)
    max_executions_per_run: int = Field(gt=0)
    proxy_pricing: Literal["api_list_rates"] = "api_list_rates"
    hard_stop_proxy_cost_per_run_usd: float = Field(gt=0)


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
    path: str = "state/events.jsonl"


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
        if v.provider == "claude" and v.claude is None:
            raise ValueError("reviewer.provider=claude requires reviewer.claude")
        return v


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
