from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.events.log import EventLog
from runtime.events.schema import Event, EventType
from runtime.init import service
from runtime.init import command
from runtime.repo.git_adapter import GitCliAdapter
from runtime.workspace_lease import LeaseState


def _run(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"setup git {args} failed: {p.stderr}")
    return p.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A real temp repo on branch 'main' with one seed commit, for tests
    that need genuine Git semantics (tip preservation, real conflicts) a
    fake adapter cannot meaningfully prove."""
    repo_dir = tmp_path / "target"
    repo_dir.mkdir()
    _run(repo_dir, "init", "-b", "main")
    _run(repo_dir, "config", "core.autocrlf", "false")
    (repo_dir / "README").write_text("seed\n")
    _run(repo_dir, "add", "-A")
    _run(repo_dir, "commit", "-m", "seed")
    return repo_dir


def _real_yaml(repo: Path, branch: str) -> str:
    return f'''project:
  name: target
  repository: "{repo.as_posix()}"
  branch: {branch}
  validation:
    commands: ["python -m pytest tests/unit/test_x.py"]
engine:
  provider: claude-headless
  auth_mode: subscription
reviewer:
  provider: qwen
  qwen: {{endpoint: "http://localhost:11434", model: qwen2.5-coder:14b}}
budget: {{max_attempts_per_issue: 1, max_executions_per_run: 1, hard_stop_proxy_cost_per_run_usd: 1}}
experiment: {{sample_size: 20, attempt1_success_min: 0.3, cost_per_shipped_issue_max_usd: 3}}
billing: {{posture: x, headless_split_status: x, verified_on: "2026-08-29", reverify_at: x}}
'''


def _real_apply(repo: Path, branch: str, *, monkeypatch, published=None) -> service.TargetConfigurationResult:
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])
    request = service.TargetConfigurationRequest(
        repo, _real_yaml(repo, branch), None, branch_change_confirmed=True, manage_branch=True,
    )
    return service.apply_target_configuration(
        request,
        publisher=(lambda path, text: published.append((path, text))) if published is not None else (lambda *_: None),
    )


class _Lease:
    def __init__(self, state=LeaseState.ACQUIRED):
        self.state = state
        self.detail = "test lease"
        self.released = False

    def release_and_close(self):
        self.released = True


class _Status:
    def __init__(self, blocking=False):
        self.blocking = blocking


class _Adapter:
    def __init__(self, blocking=False):
        self.blocking = blocking
        self.calls = 0

    def worktree_status(self):
        self.calls += 1
        return _Status(self.blocking)


class _BranchTrackingAdapter:
    def __init__(self, existing_head=None, blocking=False):
        self.existing_head = existing_head
        self.blocking = blocking
        self.checkout_calls = []
        self.status_calls = 0

    def worktree_status(self):
        self.status_calls += 1
        return _Status(self.blocking)

    def head_of(self, branch):
        return self.existing_head

    def current_commit(self):
        return "deadbeef" * 5

    def checkout_branch(self, branch, *, create_from=None, allow_untracked=False):
        self.checkout_calls.append((branch, create_from, allow_untracked))


def _yaml(repo: Path) -> str:
    return f'''project:
  name: target
  repository: "{repo.as_posix()}"
  branch: main
  validation:
    commands: ["python -m pytest tests/unit/test_x.py"]
engine:
  provider: claude-headless
  auth_mode: subscription
reviewer:
  provider: qwen
  qwen: {{endpoint: "http://localhost:11434", model: qwen2.5-coder:14b}}
budget: {{max_attempts_per_issue: 1, max_executions_per_run: 1, hard_stop_proxy_cost_per_run_usd: 1}}
experiment: {{sample_size: 20, attempt1_success_min: 0.3, cost_per_shipped_issue_max_usd: 3}}
billing: {{posture: x, headless_split_status: x, verified_on: "2026-08-29", reverify_at: x}}
'''


def _request(repo: Path) -> service.TargetConfigurationRequest:
    return service.TargetConfigurationRequest(repo, _yaml(repo), None, manage_branch=False)


def test_apply_rejects_dirty_worktree_inside_shared_service(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease()
    published = []
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease,
            adapter_factory=lambda _: _Adapter(blocking=True),
            publisher=lambda path, text: published.append((path, text)),
        )

    assert exc_info.value.code == "DIRTY_WORKTREE"
    assert published == []
    assert lease.released is True


def test_apply_is_the_only_publisher_path_and_rechecks_before_write(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease()
    adapter = _Adapter()
    published = []
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    result = service.apply_target_configuration(
        _request(repo), lease_factory=lambda _: lease, adapter_factory=lambda _: adapter,
        publisher=lambda path, text: published.append((path, text)),
    )

    assert result.config_path == repo / ".draindeck" / "config.local.yaml"
    assert len(published) == 1
    assert adapter.calls == 2


def test_prepare_is_read_only_and_witnesses_existing_digest(tmp_path):
    repo = tmp_path / "repo"
    config = repo / ".draindeck" / "config.local.yaml"
    (repo / ".git").mkdir(parents=True)
    config.parent.mkdir()
    config.write_text("old", encoding="utf-8")

    preview = service.prepare_target_configuration(_request(repo))

    assert preview.current_config_digest is not None
    assert config.read_text(encoding="utf-8") == "old"


def test_cli_and_dashboard_bind_the_identical_shared_apply_function():
    """A future adapter bypass fails here instead of silently drifting policy."""
    assert command.apply_target_configuration is service.apply_target_configuration
    dashboard_source = (Path(__file__).parents[2] / "src" / "draindeck_dashboard" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "from runtime.init.service import (" in dashboard_source
    assert "apply_target_configuration," in dashboard_source
    assert "result = apply_target_configuration(TargetConfigurationRequest(" in dashboard_source


# todo.md: "Architecture tests forbid CLI/Dashboard adapters from directly
# importing or calling GitCliAdapter, WorkspaceLease, config write helpers,
# os.replace, or write-mode filesystem APIs." This is the regression guard
# for the exact gap a fresh-context review found: command.py's cmd_init used
# to call GitCliAdapter/checkout_branch directly for its own branch/dirty
# handling, entirely bypassing the shared service for that half of the
# mutation (ADR-29's "CLI vs Dashboard apply" row was false until fixed).
_FORBIDDEN_IMPORTS = (
    "from ..repo.git_adapter import",
    "from ...runtime.repo.git_adapter import",
    "from runtime.repo.git_adapter import",
    "import runtime.repo.git_adapter",
    "from ..workspace_lease import",
    "from runtime.workspace_lease import",
    "import runtime.workspace_lease",
    "from .generate import write_config",
    "from runtime.init.generate import write_config",
    "os.replace",
)


def test_cli_adapter_has_no_direct_git_lease_or_write_policy_path():
    source = (Path(__file__).parents[2] / "src" / "runtime" / "init" / "command.py").read_text(
        encoding="utf-8"
    )
    hits = [needle for needle in _FORBIDDEN_IMPORTS if needle in source]
    assert hits == []


def test_dashboard_adapter_has_no_direct_git_lease_or_write_policy_path():
    source = (Path(__file__).parents[2] / "src" / "draindeck_dashboard" / "app.py").read_text(
        encoding="utf-8"
    )
    hits = [needle for needle in _FORBIDDEN_IMPORTS if needle in source]
    assert hits == []


# ── lease unavailable / lease error fail closed (outcome matrix) ───────

def test_apply_returns_typed_error_for_unavailable_lease(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease(state=LeaseState.UNAVAILABLE)

    def _unreachable(*_a, **_kw):
        raise AssertionError("must not be reached when the lease is unavailable")

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease,
            adapter_factory=_unreachable, publisher=_unreachable,
        )

    assert exc_info.value.code == "WORKSPACE_LEASE_UNAVAILABLE"
    assert lease.released is True


def test_apply_returns_typed_error_for_lease_acquisition_error(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease(state=LeaseState.ERROR)

    def _unreachable(*_a, **_kw):
        raise AssertionError("must not be reached when lease acquisition errors")

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease,
            adapter_factory=_unreachable, publisher=_unreachable,
        )

    assert exc_info.value.code == "WORKSPACE_LEASE_UNAVAILABLE"
    assert lease.released is True


# ── unresolved execution / unreleased containment fail closed ──────────

def test_apply_returns_runtime_state_unsafe_for_open_execution(tmp_path, monkeypatch):
    """Outcome matrix: 'Unresolved execution / containment / active run ->
    RUNTIME_STATE_UNSAFE; no config file is created or replaced.'"""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    log_path = repo / ".draindeck" / "state" / "events.jsonl"
    with EventLog(log_path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042"))
        log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="042",
                         execution_id="042-e1", payload={"spawn_reason": "initial"}))
    lease = _Lease()
    adapter = _Adapter()
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    def _unreachable(*_a, **_kw):
        raise AssertionError("publisher must not be called with an open execution")

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease, adapter_factory=lambda _: adapter,
            publisher=_unreachable,
        )

    assert exc_info.value.code == "RUNTIME_STATE_UNSAFE"
    assert not (repo / ".draindeck" / "config.local.yaml").exists()


# ── missing branch confirmation causes zero mutation ────────────────────

def test_missing_branch_confirmation_performs_zero_git_or_publish_mutation(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    adapter = _BranchTrackingAdapter(existing_head=None)
    published = []
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            service.TargetConfigurationRequest(repo, _yaml(repo), None),
            lease_factory=lambda _: _Lease(), adapter_factory=lambda _: adapter,
            publisher=lambda path, text: published.append((path, text)),
        )

    assert exc_info.value.code == "BRANCH_CONFIRMATION_REQUIRED"
    assert adapter.checkout_calls == []
    assert published == []


# ── published config round-trips through load_config, rejects unknown fields ──

def test_published_config_round_trips_through_load_config_and_rejects_unknown_fields(git_repo, monkeypatch):
    from runtime.config import ConfigError, load_config

    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])
    request = service.TargetConfigurationRequest(
        git_repo, _real_yaml(git_repo, "agent-work"), None,
        branch_change_confirmed=True, manage_branch=True,
    )
    service.apply_target_configuration(request)  # real publisher: actually writes
    dest = git_repo / ".draindeck" / "config.local.yaml"

    loaded = load_config(dest)
    assert loaded.project.branch == "agent-work"

    dest.write_text(dest.read_text(encoding="utf-8") + "unknown_field: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(dest)


def test_dashboard_branch_operation_requires_confirmation_inside_shared_service(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            service.TargetConfigurationRequest(repo, _yaml(repo), None),
            lease_factory=lambda _: _Lease(), adapter_factory=lambda _: _Adapter(),
            publisher=lambda *_: None,
        )

    assert exc_info.value.code == "BRANCH_CONFIRMATION_REQUIRED"


def test_apply_rejects_digest_conflict_before_any_branch_mutation(tmp_path, monkeypatch):
    """Outcome matrix: 'Digest mismatch before apply -> CONFIG_REVISION_CONFLICT;
    old config and branch remain unchanged.' A stale/mismatched expected digest
    must refuse before the branch is created or switched, even when a branch
    change is also needed and confirmed."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease()
    adapter = _BranchTrackingAdapter(existing_head=None)
    published = []
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    request = service.TargetConfigurationRequest(
        repo, _yaml(repo), "0" * 64, branch_change_confirmed=True, manage_branch=True,
    )

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            request, lease_factory=lambda _: lease, adapter_factory=lambda _: adapter,
            publisher=lambda path, text: published.append((path, text)),
        )

    assert exc_info.value.code == "CONFIG_REVISION_CONFLICT"
    assert published == []
    assert adapter.checkout_calls == []


def test_apply_returns_recovery_required_for_abandoned_lease(tmp_path):
    """Outcome matrix: 'Abandoned lease -> RECOVERY_REQUIRED; service releases
    it and performs no recovery or write.'"""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    lease = _Lease(state=LeaseState.ABANDONED_ACQUIRED)

    def _unreachable(*_a, **_kw):
        raise AssertionError("must not be reached for an abandoned lease")

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease,
            adapter_factory=_unreachable, publisher=_unreachable,
        )

    assert exc_info.value.code == "RECOVERY_REQUIRED"
    assert lease.released is True


def test_apply_returns_runtime_state_unsafe_for_corrupt_authoritative_log(tmp_path, monkeypatch):
    """Outcome matrix: 'Torn or corrupt authoritative log -> RUNTIME_STATE_UNSAFE;
    log bytes remain untouched.'"""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    log_path = repo / ".draindeck" / "state" / "events.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("not a valid event line\n", encoding="utf-8")
    lease = _Lease()
    adapter = _Adapter()
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])

    def _unreachable(*_a, **_kw):
        raise AssertionError("publisher must not be called for unsafe runtime state")

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.apply_target_configuration(
            _request(repo), lease_factory=lambda _: lease, adapter_factory=lambda _: adapter,
            publisher=_unreachable,
        )

    assert exc_info.value.code == "RUNTIME_STATE_UNSAFE"
    assert log_path.read_text(encoding="utf-8") == "not a valid event line\n"


# ── real-Git branch mechanics, orchestrated by the shared service ──────
# These replace command.py's former direct-adapter setup_branch tests: the
# CLI no longer performs its own branch mutation (ADR-29 full migration),
# so the guarantee now lives here, proven end-to-end through the service.

def test_apply_creates_new_branch_at_current_head(git_repo, monkeypatch):
    adapter = GitCliAdapter(git_repo)
    head = adapter.current_commit()

    result = _real_apply(git_repo, "agent-work", monkeypatch=monkeypatch)

    assert result.branch_operation == "CREATE"
    assert result.branch_tip == head
    assert adapter.head_of("agent-work") == head


def test_apply_preserves_existing_branch_tip_no_force_reset(git_repo, monkeypatch):
    adapter = GitCliAdapter(git_repo)
    adapter.checkout_branch("agent-work", create_from=adapter.current_commit())
    (git_repo / "extra.txt").write_text("work in progress\n")
    _run(git_repo, "add", "-A")
    _run(git_repo, "commit", "-m", "prior work on agent-work")
    preserved_tip = adapter.current_commit()
    adapter.checkout_branch("main")  # simulate a fresh `init` invocation

    result = _real_apply(git_repo, "agent-work", monkeypatch=monkeypatch)

    assert result.branch_operation == "CHECKOUT"
    assert result.branch_tip == preserved_tip
    assert adapter.head_of("agent-work") == preserved_tip
    assert (git_repo / "extra.txt").exists()


def test_apply_allows_untracked_only_during_branch_setup(git_repo, monkeypatch):
    (git_repo / "Issues.md").write_text("scratch\n")  # untracked

    result = _real_apply(git_repo, "agent-work", monkeypatch=monkeypatch)

    assert result.branch_operation == "CREATE"
    assert (git_repo / "Issues.md").read_text() == "scratch\n"


def test_apply_wraps_branch_checkout_conflict_as_typed_error_no_mutation(git_repo, monkeypatch):
    """A real Git checkout refusal (untracked file would be overwritten by
    the target branch) must surface as a typed TargetConfigurationError, not
    a raw RepoError -- and must leave the worktree/branch untouched."""
    adapter = GitCliAdapter(git_repo)
    trunk_tip = adapter.current_commit()
    adapter.checkout_branch("agent-work", create_from=trunk_tip)
    (git_repo / "conflicting.txt").write_text("tracked on agent-work\n")
    _run(git_repo, "add", "-A")
    _run(git_repo, "commit", "-m", "add conflicting.txt on agent-work")
    adapter.checkout_branch("main")
    (git_repo / "conflicting.txt").write_text("untracked local content\n")
    published = []

    with pytest.raises(service.TargetConfigurationError) as exc_info:
        _real_apply(git_repo, "agent-work", monkeypatch=monkeypatch, published=published)

    assert exc_info.value.code == "BRANCH_OPERATION_FAILED"
    assert published == []
    assert (git_repo / "conflicting.txt").read_text() == "untracked local content\n"
    assert adapter.current_commit() == trunk_tip


# ── check_repository_ready: CLI/Dashboard early, read-only fail-fast gate ──

def test_check_repository_ready_rejects_non_git_path(tmp_path):
    with pytest.raises(service.TargetConfigurationError) as exc_info:
        service.check_repository_ready(tmp_path / "not-a-repo", tmp_path / "config.local.yaml")

    assert exc_info.value.code == "CONFIG_INVALID"


def test_check_repository_ready_reports_blocking_dirty_tree(git_repo):
    (git_repo / "README").write_text("locally modified\n")  # tracked, unstaged

    readiness = service.check_repository_ready(git_repo, git_repo / "config.local.yaml")

    assert readiness.worktree_status.blocking is True


def test_check_repository_ready_reports_untracked_only_with_count(git_repo):
    (git_repo / "Issues.md").write_text("scratch notes\n")

    readiness = service.check_repository_ready(git_repo, git_repo / "config.local.yaml")

    assert readiness.worktree_status.blocking is False
    assert readiness.worktree_status.untracked_only is True
    assert readiness.worktree_status.untracked_count == 1
    assert (git_repo / "Issues.md").read_text() == "scratch notes\n"  # left untouched


def test_check_repository_ready_reports_config_existence(git_repo):
    dest = git_repo / "config.local.yaml"

    assert service.check_repository_ready(git_repo, dest).config_exists is False

    dest.write_text("existing: true\n")

    assert service.check_repository_ready(git_repo, dest).config_exists is True


# ── force-overwrite of an unparseable existing config must not be blocked ──

def test_apply_treats_unparseable_existing_config_as_unknown_prior_branch(git_repo, monkeypatch):
    """`draindeck init --force` must be able to blast through a pre-existing,
    invalid/garbage config file -- there is no valid prior branch to protect
    once that file is already known-invalid (see _existing_branch)."""
    dest = git_repo / ".draindeck" / "config.local.yaml"
    dest.parent.mkdir(parents=True)
    dest.write_text("not: a valid draindeck config\n", encoding="utf-8")
    monkeypatch.setattr(service, "validate_environment", lambda cfg: [])
    request = service.TargetConfigurationRequest(
        git_repo, _real_yaml(git_repo, "agent-work"),
        service._digest_bytes(dest.read_bytes()),
        branch_change_confirmed=True, manage_branch=True, config_path=dest,
    )

    result = service.apply_target_configuration(request)

    assert result.branch_operation == "CREATE"
