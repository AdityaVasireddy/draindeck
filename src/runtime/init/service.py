"""Shared controlled-write boundary for CLI and Dashboard target setup."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yaml

from ..config import Config, ConfigError, resolve_event_log_path, validate_environment
from ..events.log import ReadOnlyEventLog
from ..repo.git_adapter import GitCliAdapter, WorktreeStatus
from ..repo.adapter import RepoError
from ..workspace_lease import LeaseState, WorkspaceLease
from .generate import write_config


class TargetConfigurationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TargetConfigurationRequest:
    repository_path: Path
    rendered_yaml: str
    expected_config_digest: Optional[str]
    branch_change_confirmed: bool = False
    config_path: Optional[Path] = None
    manage_branch: bool = True


@dataclass(frozen=True)
class TargetConfigurationPreview:
    config_path: Path
    current_config_digest: Optional[str]
    proposed_config_digest: str
    rendered_yaml: str
    resolved_log_path: Path


@dataclass(frozen=True)
class TargetConfigurationResult:
    config_path: Path
    config_digest: str
    resolved_log_path: Path
    branch_operation: str
    branch_tip: Optional[str] = None


@dataclass(frozen=True)
class RepositoryReadiness:
    """Read-only pre-check for CLI/Dashboard UX gating (fail fast, before any
    interactive work or side-effecting install step). This never substitutes
    for apply_target_configuration's own authoritative, immediately-before-
    mutation rechecks -- it exists purely so a caller can refuse early."""

    worktree_status: WorktreeStatus
    config_exists: bool


def canonical_config_path(repository_path: Path) -> Path:
    return repository_path / ".draindeck" / "config.local.yaml"


def check_repository_ready(
    repository_path: Path,
    config_path: Path,
    *,
    adapter_factory: Callable[[Path], GitCliAdapter] = GitCliAdapter,
) -> RepositoryReadiness:
    """The sole read-only Git-touching entry point for CLI/Dashboard early
    gating. Constructs no lease and performs no mutation."""
    try:
        adapter = adapter_factory(repository_path)
    except RepoError as exc:
        raise TargetConfigurationError("CONFIG_INVALID", str(exc)) from exc
    return RepositoryReadiness(
        worktree_status=adapter.worktree_status(),
        config_exists=config_path.is_file(),
    )


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_rendered_config(text: str) -> Config:
    try:
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise ConfigError("rendered configuration top level must be a mapping")
        return Config.model_validate(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise TargetConfigurationError("CONFIG_INVALID", str(exc)) from exc
    except Exception as exc:
        raise TargetConfigurationError("CONFIG_INVALID", str(exc)) from exc


def prepare_target_configuration(request: TargetConfigurationRequest) -> TargetConfigurationPreview:
    """Read-only validation and exact revision witness for an apply request."""
    repo = request.repository_path.resolve()
    if not repo.is_absolute() or not repo.is_dir() or not (repo / ".git").exists():
        raise TargetConfigurationError("CONFIG_INVALID", "repository_path must be an existing Git worktree")
    config = _parse_rendered_config(request.rendered_yaml)
    if Path(config.project.repository).resolve() != repo:
        raise TargetConfigurationError("CONFIG_INVALID", "project.repository must equal repository_path")
    config_path = (request.config_path or canonical_config_path(repo)).resolve()
    current = config_path.read_bytes() if config_path.is_file() else None
    return TargetConfigurationPreview(
        config_path=config_path,
        current_config_digest=_digest_bytes(current) if current is not None else None,
        proposed_config_digest=_digest_bytes(request.rendered_yaml.encode("utf-8")),
        rendered_yaml=request.rendered_yaml,
        resolved_log_path=resolve_event_log_path(config),
    )


def _assert_safe_state(config: Config) -> None:
    log_path = resolve_event_log_path(config)
    if not log_path.exists():
        return
    try:
        # Import only when an existing authoritative log needs replay.  This
        # keeps first-time configuration independent from the runtime loop's
        # optional state-machine package while preserving strict replay when
        # history exists.
        from ..events.projections import StateProjection
        with ReadOnlyEventLog(log_path) as log:
            projection = StateProjection().rebuild(log.replay())
    except Exception as exc:
        raise TargetConfigurationError("RUNTIME_STATE_UNSAFE", f"authoritative log is unsafe: {exc}") from exc
    if projection.open_executions() or projection.unreleased_containments():
        raise TargetConfigurationError("RUNTIME_STATE_UNSAFE", "runtime state has unresolved execution or containment")


def _existing_branch(config_path: Path) -> Optional[str]:
    """An unparseable existing file is treated as unknown prior state, same
    as no existing config -- not a hard failure. The branch-confirmation gate
    below still protects against a surprise branch change either way, and
    there is no valid prior branch to protect once the file is already
    known-invalid."""
    if not config_path.is_file():
        return None
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return Config.model_validate(raw).project.branch
    except Exception:
        return None


def apply_target_configuration(
    request: TargetConfigurationRequest,
    *,
    lease_factory: Callable[[Path], WorkspaceLease] = WorkspaceLease.acquire,
    adapter_factory: Callable[[Path], GitCliAdapter] = GitCliAdapter,
    publisher: Callable[[Path, str], None] = write_config,
) -> TargetConfigurationResult:
    """The only policy-owned config writer.  All refusals precede publishing."""
    preview = prepare_target_configuration(request)
    lease = lease_factory(request.repository_path)
    if lease.state is LeaseState.ABANDONED_ACQUIRED:
        try:
            raise TargetConfigurationError("RECOVERY_REQUIRED", lease.detail)
        finally:
            lease.release_and_close()
    if lease.state is not LeaseState.ACQUIRED:
        try:
            raise TargetConfigurationError("WORKSPACE_LEASE_UNAVAILABLE", lease.detail)
        finally:
            lease.release_and_close()
    try:
        try:
            adapter = adapter_factory(request.repository_path)
        except RepoError as exc:
            raise TargetConfigurationError("CONFIG_INVALID", str(exc)) from exc
        if adapter.worktree_status().blocking:
            raise TargetConfigurationError("DIRTY_WORKTREE", "tracked, staged, deleted, renamed, or conflicted changes block configuration")
        config = _parse_rendered_config(request.rendered_yaml)
        _assert_safe_state(config)
        # Digest conflict must refuse before any Git mutation (outcome matrix:
        # "old config and branch remain unchanged" on a stale/mismatched digest).
        current = preview.config_path.read_bytes() if preview.config_path.is_file() else None
        current_digest = _digest_bytes(current) if current is not None else None
        if current_digest != request.expected_config_digest:
            raise TargetConfigurationError("CONFIG_REVISION_CONFLICT", "config changed since its preview")
        branch_operation = "NONE"
        branch_tip: Optional[str] = None
        prior_branch = _existing_branch(preview.config_path) if request.manage_branch else None
        branch_change_needed = request.manage_branch and prior_branch != config.project.branch
        if branch_change_needed:
            if not request.branch_change_confirmed:
                raise TargetConfigurationError(
                    "BRANCH_CONFIRMATION_REQUIRED",
                    "creating or switching the target branch requires explicit confirmation",
                )
            # Recheck immediately before the first irreversible operation.
            if adapter.worktree_status().blocking:
                raise TargetConfigurationError("DIRTY_WORKTREE", "worktree changed during configuration")
            try:
                existing_tip = adapter.head_of(config.project.branch)
                if existing_tip is None:
                    adapter.checkout_branch(
                        config.project.branch,
                        create_from=adapter.current_commit(),
                        allow_untracked=True,
                    )
                    branch_operation = "CREATE"
                else:
                    adapter.checkout_branch(config.project.branch, allow_untracked=True)
                    branch_operation = "CHECKOUT"
            except RepoError as exc:
                raise TargetConfigurationError("BRANCH_OPERATION_FAILED", str(exc)) from exc
        if request.manage_branch:
            branch_tip = adapter.head_of(config.project.branch)
        # validate_environment's branch-existence check can only pass once a
        # newly created branch actually exists, so it necessarily runs after
        # the branch operation above for the CREATE case; it still precedes
        # the irreversible config write.
        environment_problems = validate_environment(config)
        if environment_problems:
            raise TargetConfigurationError("ENVIRONMENT_INVALID", "; ".join(environment_problems))
        # Recheck immediately before the irreversible publication boundary.
        if adapter.worktree_status().blocking:
            raise TargetConfigurationError("DIRTY_WORKTREE", "worktree changed during configuration")
        publisher(preview.config_path, preview.rendered_yaml)
        return TargetConfigurationResult(
            preview.config_path, preview.proposed_config_digest, preview.resolved_log_path,
            branch_operation, branch_tip,
        )
    except TargetConfigurationError:
        raise
    except OSError as exc:
        raise TargetConfigurationError("CONFIG_PUBLICATION_FAILED", str(exc)) from exc
    finally:
        lease.release_and_close()
