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
# runtime.init.service (ADR-29) is the sole approved gate onto Git/workspace
# lease mutation; nothing else in the Dashboard may import those modules.
_GIT_LEASE_MODULES = {
    "runtime.repo.git_adapter",
    "runtime.workspace_lease",
}
_GIT_LEASE_ALLOWED_FILES: set[str] = set()  # nothing imports these directly today


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
        hit = _imported_dotted_modules(py_file) & _GIT_LEASE_MODULES
        if hit:
            offenders.append((str(py_file.relative_to(REPO_ROOT)), sorted(hit)))
    assert offenders == [], (
        f"Dashboard must reach Git/workspace-lease mutation only through "
        f"runtime.init.service (ADR-29): {offenders}"
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
