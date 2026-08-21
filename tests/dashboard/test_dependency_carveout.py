"""ADR-26 decision 1: core src/runtime stays framework-free. FastAPI,
Starlette, and Uvicorn are an explicit carve-out for draindeck_dashboard
only."""
from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_SRC = Path(__file__).resolve().parents[2] / "src" / "runtime"
_FORBIDDEN_MODULES = {"fastapi", "starlette", "uvicorn"}


def _imported_top_level_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_runtime_never_imports_the_web_stack():
    offenders = []
    for py_file in RUNTIME_SRC.rglob("*.py"):
        hit = _imported_top_level_modules(py_file) & _FORBIDDEN_MODULES
        if hit:
            offenders.append((str(py_file), sorted(hit)))
    assert offenders == [], f"src/runtime must stay framework-free: {offenders}"
