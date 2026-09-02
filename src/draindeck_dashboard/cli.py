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

    from pydantic import ValidationError

    from .app import create_app
    from .config import DashboardConfig, DashboardConfigError, load_dashboard_config

    ap = argparse.ArgumentParser(prog="draindeck-dashboard")
    ap.add_argument("--config", help="path to a Dashboard config YAML file")
    # In-memory alternative to --config, used by the launcher (docs/32
    # "Dashboard process settings are in-memory only") -- no config file is
    # ever read or written on this path.
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--observer-executable", default=None)
    ap.add_argument("--instance-token", default=None)
    args = ap.parse_args(argv)

    try:
        if args.config:
            cfg = load_dashboard_config(args.config)
        elif args.db_path and args.observer_executable:
            cfg = DashboardConfig(
                host=args.host if args.host is not None else "127.0.0.1",
                port=args.port if args.port is not None else 8420,
                db_path=args.db_path,
                observer_executable=args.observer_executable,
            )
        else:
            print(
                "CONFIG INVALID: either --config, or both --db-path and "
                "--observer-executable, are required",
                file=sys.stderr,
            )
            return 1
    except (DashboardConfigError, ValidationError) as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1

    app = create_app(cfg, instance_token=args.instance_token)
    uvicorn.run(app, host=cfg.host, port=cfg.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
