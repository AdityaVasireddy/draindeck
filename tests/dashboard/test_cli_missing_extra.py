"""Phase 2 requirement: `draindeck-dashboard` must fail with a clean
"install draindeck[dashboard]" message when the optional extra is absent,
not a raw ModuleNotFoundError."""
from __future__ import annotations

import sys


def test_clean_message_when_uvicorn_unavailable(monkeypatch, capsys):
    # Simulate the extra being absent without uninstalling it: setting a
    # module to None in sys.modules makes `import uvicorn` raise
    # ImportError, exactly like real absence would.
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    from draindeck_dashboard import cli

    rc = cli.main(["--config", "unused.yaml"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "pip install draindeck[dashboard]" in captured.err
    assert "ModuleNotFoundError" not in captured.err
    assert "Traceback" not in captured.err
