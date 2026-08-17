"""Stack detection for `draindeck init` (doc 16 §5). A data-driven table,
not a chain of ifs — adding a stack is a one-row change (doc 16 §12).

Detection is read-only: every function here only reads the filesystem
(`Path.exists`/`Path.glob`/`Path.rglob`). Nothing here mutates the target
repo, writes a config, runs an install, or touches the network.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_IS_WINDOWS = os.name == "nt"  # mirrors validation/runner.py:26

_VENDOR_DIR_NAMES = {"node_modules", "vendor", "dist", "build"}
_REACT_DEPS = ("react", "react-dom")


@dataclass(frozen=True)
class CommandProposal:
    """What a matched row proposes. `commands` is always non-empty when
    this is returned — an empty-commands config is never representable
    through this type (doc 16 §2/§4 step 3)."""

    commands: list[str]
    install_command: Optional[str] = None
    needs_rule2_confirm: bool = False  # ADR-23 rule 2 TODO marker (Python row)


@dataclass(frozen=True)
class DetectionRow:
    stack: str
    matches: Callable[[Path], bool]
    build: Callable[[Path], Optional[CommandProposal]]


def _invocable(interpreter: Path) -> str:
    """A quoted interpreter path usable as the leading token of a shell
    command string. PowerShell requires the call operator to invoke a
    quoted leading path — bare `"C:\\a b\\python.exe" -m pytest` is a
    parser error there (verified empirically this session); POSIX sh does
    not need it, and a leading `&` there means "run in background," so it
    must not be added on that platform."""
    quoted = f'"{interpreter}"'
    return f"& {quoted}" if _IS_WINDOWS else quoted


def resolve_interpreter(repo_path: Path) -> Optional[Path]:
    """Absolute interpreter path per ADR-23 rule 1 (doc 08 §5d): bare
    `python` resolves differently depending on shell/venv state, which
    previously flipped a validation verdict. Prefers a project venv over
    PATH resolution."""
    venv = repo_path / (".venv/Scripts/python.exe" if _IS_WINDOWS
                         else ".venv/bin/python")
    if venv.exists():
        return venv.resolve()
    found = shutil.which("python" if _IS_WINDOWS else "python3")
    return Path(found).resolve() if found else None


def enumerate_js_files(repo_path: Path) -> list[Path]:
    """`*.js` files under `repo_path`, excluding dot-directories and
    common vendor/build folder names (doc 16 §5 static-web row) — cheap
    insurance, not a new feature, since this row's own marker already
    requires no `package.json`."""
    out: list[Path] = []
    for p in sorted(repo_path.rglob("*.js")):
        rel_parts = p.relative_to(repo_path).parts[:-1]
        if any(part.startswith(".") for part in rel_parts):
            continue
        if any(part in _VENDOR_DIR_NAMES for part in rel_parts):
            continue
        out.append(p)
    return out


def _read_package_json(repo_path: Path) -> Optional[dict]:
    p = repo_path / "package.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── row matchers ─────────────────────────────────────────────────────
def _match_python(repo_path: Path) -> bool:
    return (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists()


def _match_rust(repo_path: Path) -> bool:
    return (repo_path / "Cargo.toml").exists()


def _match_node_test(repo_path: Path) -> bool:
    pkg = _read_package_json(repo_path)
    return bool(pkg and "test" in (pkg.get("scripts") or {}))


def _match_node_lint(repo_path: Path) -> bool:
    pkg = _read_package_json(repo_path)
    if not pkg:
        return False
    scripts = pkg.get("scripts") or {}
    return "lint" in scripts and "test" not in scripts


def _match_react(repo_path: Path) -> bool:
    pkg = _read_package_json(repo_path)
    if not pkg:
        return False
    scripts = pkg.get("scripts") or {}
    if "test" in scripts or "lint" in scripts:
        return False
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    return any(d in deps for d in _REACT_DEPS)


def _match_go(repo_path: Path) -> bool:
    return (repo_path / "go.mod").exists()


def _match_static_web(repo_path: Path) -> bool:
    if (repo_path / "package.json").exists():
        return False
    return any(repo_path.rglob("*.html")) and any(repo_path.rglob("*.js"))


# ── row builders ─────────────────────────────────────────────────────
def _build_python(repo_path: Path) -> Optional[CommandProposal]:
    interpreter = resolve_interpreter(repo_path)
    if interpreter is None:
        return None
    prefix = _invocable(interpreter)
    return CommandProposal(
        commands=[f"{prefix} -m pytest"],
        install_command=f"{prefix} -m pip install -r requirements.txt",
        needs_rule2_confirm=True,
    )


def _build_rust(repo_path: Path) -> CommandProposal:
    return CommandProposal(commands=["cargo test"], install_command="cargo fetch")


def _build_node_test(repo_path: Path) -> CommandProposal:
    return CommandProposal(commands=["npm test"], install_command="npm install")


def _build_node_lint(repo_path: Path) -> CommandProposal:
    return CommandProposal(commands=["npm run lint"], install_command="npm install")


def _build_react(repo_path: Path) -> CommandProposal:
    return CommandProposal(commands=["npm run build"], install_command="npm install")


def _build_go(repo_path: Path) -> CommandProposal:
    return CommandProposal(commands=["go test ./..."], install_command="go mod download")


def _build_static_web(repo_path: Path) -> Optional[CommandProposal]:
    files = enumerate_js_files(repo_path)
    if not files:
        return None
    commands = [f'node --check "{f.relative_to(repo_path).as_posix()}"' for f in files]
    return CommandProposal(commands=commands, install_command=None)


# ── the table (doc 16 §5) ────────────────────────────────────────────
TABLE: list[DetectionRow] = [
    DetectionRow("Python", _match_python, _build_python),
    DetectionRow("Rust", _match_rust, _build_rust),
    DetectionRow("Node (test)", _match_node_test, _build_node_test),
    DetectionRow("Node (lint)", _match_node_lint, _build_node_lint),
    DetectionRow("React", _match_react, _build_react),
    DetectionRow("Go", _match_go, _build_go),
    DetectionRow("Static web", _match_static_web, _build_static_web),
]


def detect_stacks(repo_path: Path, table: list[DetectionRow] = TABLE) -> list[DetectionRow]:
    """Every row whose marker matches, in table priority order. `table`
    is dependency-injected (defaulting to the real one) so a test can
    prove the "add a stack is one row" property without mutating module
    state."""
    return [row for row in table if row.matches(repo_path)]


def build_command(row: DetectionRow, repo_path: Path) -> Optional[CommandProposal]:
    return row.build(repo_path)
