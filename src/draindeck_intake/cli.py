"""Command-line composition root for explicit one-way issue intake."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from .compiler import compile_issues_md
from .github import GitHubSource
from .http import BoundedJsonTransport, JsonTransport
from .issues_md import IssuesMdSource
from .jira import JiraSource
from .linear import LinearSource
from .output import OutputError, publish_managed
from .sources import IssueSource, SourceError, collect_issues

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CliInputError(ValueError):
    """Command input is invalid without exposing raw argument values."""


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliInputError("invalid command arguments")


TransportFactory = Callable[..., JsonTransport]


def _add_common(parser: argparse.ArgumentParser, *, default_prefix: str | None) -> None:
    parser.add_argument("--output", required=True)
    parser.add_argument("--id-prefix", default=default_prefix)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-issues", type=int, default=1_000)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--force", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="draindeck-intake")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="compile a source into managed Issues.md")
    providers = sync.add_subparsers(dest="provider", required=True)

    local = providers.add_parser("issues-md", help="import a local Issues.md")
    local.add_argument("--input", required=True)
    _add_common(local, default_prefix=None)

    github = providers.add_parser("github", help="import open GitHub issues")
    github.add_argument("--owner", required=True)
    github.add_argument("--repo", required=True)
    github.add_argument("--token-env", default="GITHUB_TOKEN")
    _add_common(github, default_prefix="gh")

    jira = providers.add_parser("jira", help="import Jira Cloud JQL results")
    jira.add_argument("--base-url", required=True)
    jira.add_argument("--jql", required=True)
    jira.add_argument("--email-env", default="JIRA_EMAIL")
    jira.add_argument("--token-env", default="JIRA_API_TOKEN")
    _add_common(jira, default_prefix="jira")

    linear = providers.add_parser("linear", help="import Linear team issues")
    linear.add_argument("--team-key", required=True)
    linear.add_argument("--key-env", default="LINEAR_API_KEY")
    _add_common(linear, default_prefix="linear")
    return parser


def _environment_name(value: object) -> str:
    if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
        raise CliInputError("credential environment-variable name is invalid")
    return value


def _required_environment(environ: Mapping[str, str], name: object) -> str:
    key = _environment_name(name)
    value = environ.get(key)
    if not value:
        raise CliInputError("required credential environment variable is not set")
    return value


def _optional_environment(environ: Mapping[str, str], name: object) -> str | None:
    key = _environment_name(name)
    return environ.get(key) or None


def _validate_common(args: argparse.Namespace) -> None:
    if (
        isinstance(args.page_size, bool)
        or not isinstance(args.page_size, int)
        or not 1 <= args.page_size <= 100
    ):
        raise CliInputError("page size must be between 1 and 100")
    if (
        isinstance(args.max_issues, bool)
        or not isinstance(args.max_issues, int)
        or not 1 <= args.max_issues <= 100_000
    ):
        raise CliInputError("maximum issues must be between 1 and 100000")
    if (
        isinstance(args.timeout_seconds, bool)
        or not isinstance(args.timeout_seconds, (int, float))
        or not math.isfinite(args.timeout_seconds)
        or not 0 < args.timeout_seconds <= 300
    ):
        raise CliInputError("timeout must be finite and between 0 and 300 seconds")


def _transport(
    factory: TransportFactory,
    *,
    hosts: set[str],
    timeout_seconds: float,
) -> JsonTransport:
    return factory(allowed_hosts=hosts, timeout_seconds=timeout_seconds)


def _build_source(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    transport_factory: TransportFactory,
) -> IssueSource:
    try:
        if args.provider == "issues-md":
            return IssuesMdSource(args.input, id_prefix=args.id_prefix)
        if args.provider == "github":
            return GitHubSource(
                _transport(
                    transport_factory,
                    hosts={"api.github.com"},
                    timeout_seconds=args.timeout_seconds,
                ),
                owner=args.owner,
                repo=args.repo,
                id_prefix=args.id_prefix,
                token=_optional_environment(environ, args.token_env),
            )
        if args.provider == "jira":
            hostname = urlsplit(args.base_url).hostname or "invalid"
            return JiraSource(
                _transport(
                    transport_factory,
                    hosts={hostname},
                    timeout_seconds=args.timeout_seconds,
                ),
                base_url=args.base_url,
                jql=args.jql,
                email=_required_environment(environ, args.email_env),
                api_token=_required_environment(environ, args.token_env),
                id_prefix=args.id_prefix,
            )
        if args.provider == "linear":
            return LinearSource(
                _transport(
                    transport_factory,
                    hosts={"api.linear.app"},
                    timeout_seconds=args.timeout_seconds,
                ),
                team_key=args.team_key,
                api_key=_required_environment(environ, args.key_env),
                id_prefix=args.id_prefix,
            )
    except CliInputError:
        raise
    except SourceError as exc:
        raise CliInputError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise CliInputError("source configuration is invalid") from exc
    raise CliInputError("source provider is invalid")


def _emit_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {"error": {"code": code, "message": message}},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport_factory: TransportFactory = BoundedJsonTransport,
) -> int:
    """Run one explicit sync and return the documented process exit code."""
    try:
        args = _parser().parse_args(argv)
        _validate_common(args)
        source = _build_source(args, environ if environ is not None else os.environ, transport_factory)
        issues = collect_issues(
            source, page_size=args.page_size, max_issues=args.max_issues
        )
        output = Path(args.output).absolute()
        changed = publish_managed(
            output, compile_issues_md(issues), force=args.force
        )
    except CliInputError as exc:
        _emit_error("invalid_input", str(exc))
        return 2
    except OutputError as exc:
        _emit_error("output_error", str(exc))
        return 1
    except SourceError as exc:
        _emit_error("source_error", str(exc))
        return 1
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        _emit_error("internal_error", "unexpected internal failure")
        return 1

    print(
        json.dumps(
            {
                "contractVersion": 1,
                "source": source.name,
                "issueCount": len(issues),
                "outputPath": str(output),
                "changed": changed,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
