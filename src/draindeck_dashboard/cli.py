"""Console-script entrypoint for ``draindeck-dashboard``.

Fails with a clean, actionable message — never a raw ``ModuleNotFoundError``
— when the optional ``dashboard`` extra (FastAPI/Uvicorn) is not installed.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "draindeck-dashboard requires the optional 'dashboard' extra.\n"
            "Install it with: pip install draindeck[dashboard]",
            file=sys.stderr,
        )
        return 1

    from .app import create_app
    from .config import DashboardConfigError, load_dashboard_config

    ap = argparse.ArgumentParser(prog="draindeck-dashboard")
    ap.add_argument("--config", required=True)
    args = ap.parse_args(argv)

    try:
        cfg = load_dashboard_config(args.config)
    except DashboardConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
