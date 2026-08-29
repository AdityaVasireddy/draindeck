"""ADR-28 dependency direction: runtime never depends on optional Intake."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTAKE = ROOT / "src" / "draindeck_intake"
RUNTIME = ROOT / "src" / "runtime"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_runtime_never_imports_optional_intake() -> None:
    offenders = [
        str(path)
        for path in RUNTIME.rglob("*.py")
        if any(name == "draindeck_intake" or name.startswith("draindeck_intake.") for name in _imports(path))
    ]
    assert offenders == []


def test_intake_runtime_import_is_limited_to_the_pure_issues_parser() -> None:
    runtime_imports = {
        (path.relative_to(ROOT).as_posix(), name)
        for path in INTAKE.rglob("*.py")
        for name in _imports(path)
        if name == "runtime" or name.startswith("runtime.")
    }
    assert runtime_imports == {
        ("src/draindeck_intake/issues_md.py", "runtime.queue.issues_md")
    }
