"""ADR-30 (docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md,
docs/08 Sec 5l) RED 0: architecture and frozen-contract gate.

Five of these six checks are architecture-invariant regression guards: the
boundary they assert already holds today (no run-control code exists yet to
violate it), so they pass on first run rather than failing RED-first. Writing
them now, before any feature code, is what "gate" means here -- they must
still be green after every later unit. Only
`test_dashboard_control_requires_accepted_adr_and_updated_product_boundary`
has genuine production content to drive (the package docstring must stop
claiming pure read-only status once ADR-30 is accepted). See
docs/plans/dashboard-issue-run-control-failing-tests.md RED 0 for the planned
inventory this file implements.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_SRC = REPO_ROOT / "src" / "draindeck_dashboard"
RUNTIME_SRC = REPO_ROOT / "src" / "runtime"

# observer_client.py IS the approved boundary: it shells out to the read-only
# `draindeck observe` CLI (ADR-25) instead of touching events.jsonl itself.
_EVENTS_JSONL_ALLOWED_FILES = {
    DASHBOARD_SRC / "observer_client.py",
    DASHBOARD_SRC / "__init__.py",  # package docstring names the boundary in prose
}
# runtime.init.service (ADR-29) is the sole approved gate onto Git mutation;
# runtime.repo.git_adapter is banned outright. runtime.workspace_lease is
# narrower: only its MUTATING surface (acquiring/releasing/repairing the
# lease) is banned. ADR-30 decision 4 explicitly permits the Dashboard to
# observe a recorded PID/creation-time identity ("control-plane information,
# not workflow state, and grants no authority to acquire or repair the
# runtime lease") via the exact same read-only probe runtime.workspace_lease
# already uses for its own orphan detection -- reusing it is the point, not
# a violation, so those specific read-only names are allowed.
_WORKSPACE_LEASE_READONLY_NAMES = {
    "probe_controller_identity", "ControllerIdentityResult", "ControllerIdentityState",
    "WindowsProcessIdentityApi",
}
# runtime.repo.git_adapter is a mutation-capable module (checkout/merge/reset).
# Only its read-only worktree-status witness may be imported by name into the
# Dashboard -- the clean-worktree launch preflight (doc 33 Part A) -- exactly
# mirroring the workspace-lease read-only carve-out above. GitCliAdapter itself
# and every mutation entrypoint stay banned, and a plain `import
# runtime.repo.git_adapter` (which would expose the whole module) is banned too.
_GIT_ADAPTER_READONLY_NAMES = {"read_worktree_status", "WorktreeStatus"}
_GIT_LEASE_ALLOWED_FILES: set[str] = set()  # nothing imports these directly today


def _plain_imported_modules(py_file: Path) -> set[str]:
    """Dotted module names bound by a plain ``import X`` (not ``from X import
    ...``) -- a plain import exposes the whole module's attribute surface, so
    it cannot be restricted to read-only names."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def _imported_names_from(py_file: Path, module: str) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names |= {alias.name for alias in node.names}
    return names


def _py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imported_dotted_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_dashboard_control_requires_accepted_adr_and_updated_product_boundary():
    adr = (REPO_ROOT / "docs" / "adr"
           / "ADR-30-dashboard-issue-selection-and-run-control.md").read_text(encoding="utf-8")
    status_line = adr.splitlines()[2]
    assert "ACCEPTED" in status_line, "ADR-30 must be ACCEPTED before this gate can be green"

    boundary = (DASHBOARD_SRC / "__init__.py").read_text(encoding="utf-8")
    assert "ADR-30" in boundary, (
        "the package docstring must name ADR-30 once the Dashboard gains launch capability"
    )
    assert "read-only observability UI" not in boundary, (
        "the product boundary claim must be updated -- the Dashboard is no longer purely "
        "read-only once ADR-30 is accepted"
    )


def test_core_runtime_does_not_import_fastapi_or_dashboard_modules():
    forbidden = {"fastapi", "starlette", "uvicorn", "draindeck_dashboard"}
    offenders = []
    for py_file in _py_files(RUNTIME_SRC):
        hit = {m.split(".")[0] for m in _imported_dotted_modules(py_file)} & forbidden
        if hit:
            offenders.append((str(py_file.relative_to(REPO_ROOT)), sorted(hit)))
    assert offenders == [], f"src/runtime must stay framework- and Dashboard-free: {offenders}"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id()s of the string-constant nodes that are docstrings (the first
    statement of the module or any function/class body) -- excluded from the
    literal-scan below so documenting the boundary in prose (e.g. "this
    table is never written to events.jsonl") isn't mistaken for code that
    touches the file. Comments are never part of the AST at all, so they
    need no special handling here."""
    ids: set[int] = set()
    candidates = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in candidates:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def test_dashboard_never_writes_or_parses_events_jsonl_directly():
    forbidden_modules = {"runtime.events.log", "runtime.events.readonly_log"}
    offenders = []
    for py_file in _py_files(DASHBOARD_SRC):
        if py_file in _EVENTS_JSONL_ALLOWED_FILES:
            continue
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
        docstring_ids = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and "events.jsonl" in node.value and id(node) not in docstring_ids):
                offenders.append((str(py_file.relative_to(REPO_ROOT)), "literal events.jsonl"))
                break
        hit = _imported_dotted_modules(py_file) & forbidden_modules
        if hit:
            offenders.append((str(py_file.relative_to(REPO_ROOT)), sorted(hit)))
    assert offenders == [], f"Dashboard must never touch events.jsonl directly: {offenders}"


def test_dashboard_does_not_mutate_git_target_or_workspace_lease():
    offenders = []
    for py_file in _py_files(DASHBOARD_SRC):
        if py_file.name in _GIT_LEASE_ALLOWED_FILES:
            continue
        # git_adapter: a plain module import exposes everything -> banned; a
        # `from ... import <name>` is allowed only for the read-only names.
        if "runtime.repo.git_adapter" in _plain_imported_modules(py_file):
            offenders.append((str(py_file.relative_to(REPO_ROOT)),
                              ["plain import runtime.repo.git_adapter"]))
        mutating_git_names = (
            _imported_names_from(py_file, "runtime.repo.git_adapter") - _GIT_ADAPTER_READONLY_NAMES
        )
        if mutating_git_names:
            offenders.append((str(py_file.relative_to(REPO_ROOT)),
                              sorted(f"git_adapter.{n}" for n in mutating_git_names)))
        mutating_lease_names = (
            _imported_names_from(py_file, "runtime.workspace_lease") - _WORKSPACE_LEASE_READONLY_NAMES
        )
        if mutating_lease_names:
            offenders.append((str(py_file.relative_to(REPO_ROOT)),
                              sorted(f"workspace_lease.{n}" for n in mutating_lease_names)))
    assert offenders == [], (
        f"Dashboard must reach Git/workspace-lease mutation only through "
        f"runtime.init.service (ADR-29); only the read-only process-identity "
        f"probe and the read-only worktree-status witness may be imported "
        f"directly from runtime.workspace_lease / runtime.repo.git_adapter: {offenders}"
    )


def test_no_new_run_lifecycle_payload_key_without_doc03_amendment():
    import sys
    sys.path.insert(0, str(RUNTIME_SRC.parent))
    from runtime.config import Config
    from runtime.main import _config_digest, _resolve_reviewer_model, _run_started_payload

    cfg = Config.model_validate({
        "project": {"name": "T", "repository": "C:/x", "branch": "agent-work",
                     "issues_file": "Issues.md",
                     "validation": {"commands": ["echo ok"]}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription",
                   "model": "default", "max_turns": 30, "timeout_seconds": 1800},
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": "http://localhost:11434", "model": "qwen2.5-coder"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0, "proxy_pricing": "api_list_rates"},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })
    reviewer_model = _resolve_reviewer_model(cfg)
    digest = _config_digest(cfg, reviewer_model)
    payload = _run_started_payload(cfg, reviewer_model, digest)

    assert set(payload) == {"engine", "reviewer", "budget", "config_digest"}, (
        "RunStarted's closed payload must not gain a selection/queue/command-id field "
        "under ADR-30 -- that requires a separate Doc 03 amendment"
    )


def test_run_launcher_uses_fixed_argv_without_shell():
    offenders = []
    for py_file in _py_files(DASHBOARD_SRC):
        text = py_file.read_text(encoding="utf-8")
        if re.search(r"shell\s*=\s*True", text):
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"no Dashboard subprocess call may use shell=True: {offenders}"


def test_cancel_stays_a_pure_control_plane_status_flip():
    """Doc 34 RED G-1: cancel_queued_command must remain a pure Dashboard
    control-plane status flip -- it must never run the launch preflight,
    claim/launch anything, or touch runtime events / git / the workspace lease
    / a process. A static source guard so the Dashboard control boundary can
    never silently erode into cancel."""
    import ast
    import inspect
    import textwrap

    import sys
    sys.path.insert(0, str(DASHBOARD_SRC.parent))
    from draindeck_dashboard import run_queue

    # Scan the EXECUTABLE code only -- ast.unparse drops comments, and we strip
    # the docstring, so the function's own prose ("never kills a process",
    # "never parses events.jsonl") is not mistaken for a forbidden call.
    func = ast.parse(textwrap.dedent(inspect.getsource(run_queue.cancel_queued_command))).body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant)
            and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]  # drop the docstring
    code_src = ast.unparse(func)
    banned = [
        "worktree_probe", "evaluate_worktree_preflight",  # never gated by preflight
        "try_launch_next", "claim_next_launchable_command", "launch_claimed_command",
        "Popen", "kill", "terminate",  # never touches a process
        "events.jsonl", "RunFinished",  # never touches runtime events
        "acquire", "release_lease",  # never mutates the workspace lease
    ]
    offenders = [token for token in banned if token in code_src]
    assert offenders == [], (
        f"cancel_queued_command must stay a pure control-plane status flip; "
        f"found forbidden tokens: {offenders}"
    )


def test_claim_honors_persisted_queue_pause():
    """Doc 34 Amendment 1 RED G-2: the single atomic claim chokepoint must check
    the persisted per-repository queue pause, so cancel's pause can never be
    silently bypassed by the scheduler/drain/enqueue launch paths. The pause is
    a Dashboard-only table -- never referenced from src/runtime."""
    import ast
    import inspect
    import textwrap

    import sys
    sys.path.insert(0, str(DASHBOARD_SRC.parent))
    from draindeck_dashboard import run_queue

    claim_src = ast.unparse(
        ast.parse(textwrap.dedent(inspect.getsource(run_queue.claim_next_launchable_command)))
    )
    assert "is_queue_paused" in claim_src or "run_queue_pauses" in claim_src, (
        "claim_next_launchable_command must consult the persisted queue pause "
        "before claiming a QUEUED row"
    )

    # The pause table is Dashboard-only: no src/runtime file may reference it.
    offenders = []
    for py_file in _py_files(RUNTIME_SRC):
        if "run_queue_pauses" in py_file.read_text(encoding="utf-8"):
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"run_queue_pauses is Dashboard-only control state: {offenders}"


def test_run_request_wires_authoritative_worktree_preflight():
    """Doc 33 RED B-16: the run-request path must inject a real worktree probe
    into enqueue_command so the WORKTREE_NOT_CLEAN gate can never silently
    disappear -- backend enforcement is authoritative, not advisory."""
    app_src = (DASHBOARD_SRC / "app.py").read_text(encoding="utf-8")
    assert "evaluate_worktree_preflight" in app_src, (
        "app.py must import and inject the worktree preflight into the run-request path"
    )
    assert "worktree_probe" in app_src, (
        "app.py's create_run_command must pass a worktree_probe into enqueue_command"
    )
