from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.cli import run
from draindeck_intake.compiler import MANAGED_MARKER
from draindeck_intake.output import OutputError, publish_managed
from runtime.queue.issues_md import parse


def test_publish_refuses_unmanaged_files_and_symlinks(tmp_path: Path) -> None:
    output = tmp_path / "Issues.md"
    output.write_text("human backlog\n", encoding="utf-8")
    with pytest.raises(OutputError, match="unmanaged"):
        publish_managed(output, f"{MANAGED_MARKER}\n")
    assert output.read_text(encoding="utf-8") == "human backlog\n"

    output.write_text(f"{MANAGED_MARKER}suffix\n", encoding="utf-8")
    with pytest.raises(OutputError, match="unmanaged"):
        publish_managed(output, f"{MANAGED_MARKER}\n")

    target = tmp_path / "target.md"
    target.write_text(f"{MANAGED_MARKER}\n", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(OutputError, match="symbolic link"):
        publish_managed(link, f"{MANAGED_MARKER}\n")


def test_publish_force_atomic_replace_and_identical_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "Issues.md"
    output.write_text("human backlog\n", encoding="utf-8")
    content = f"{MANAGED_MARKER}\n\n## one: First\n\nSource: issues-md:one\n"

    assert publish_managed(output, content, force=True) is True
    original_stat = output.stat()
    assert output.read_bytes() == content.encode("utf-8")
    assert publish_managed(output, content) is False
    assert output.stat().st_mtime_ns == original_stat.st_mtime_ns

    replacement = content.replace("First", "Changed")
    real_replace = os.replace

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OutputError, match="unable to publish"):
        publish_managed(output, replacement)
    assert output.read_bytes() == content.encode("utf-8")
    assert list(tmp_path.glob("*.tmp")) == []
    monkeypatch.setattr(os, "replace", real_replace)


def test_publish_refuses_a_concurrent_intake_lock(tmp_path: Path) -> None:
    output = tmp_path / "Issues.md"
    lock = tmp_path / ".Issues.md.draindeck-intake.lock"
    lock.write_text("other intake process", encoding="utf-8")
    with pytest.raises(OutputError, match="publication holds"):
        publish_managed(output, f"{MANAGED_MARKER}\n")


def test_local_cli_syncs_end_to_end_with_json_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "generated.md"
    source.write_text(
        "## two: Second\nDepends-On: one\n## one: First\nBody\n",
        encoding="utf-8",
    )

    exit_code = run(
        [
            "sync",
            "issues-md",
            "--input",
            str(source),
            "--output",
            str(output),
            "--id-prefix",
            "local",
            "--page-size",
            "1",
            "--max-issues",
            "2",
        ],
        environ={},
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result == {
        "contractVersion": 1,
        "source": "issues-md",
        "issueCount": 2,
        "outputPath": str(output.resolve()),
        "changed": True,
    }
    parsed = parse(output.read_text(encoding="utf-8"))
    assert [item.id for item in parsed] == ["local-one", "local-two"]
    assert parsed[1].depends_on == ["local-one"]


def test_cli_returns_json_input_error_without_echoing_unknown_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "never-echo-this-secret"
    exit_code = run(
        ["sync", "github", "--token", secret],
        environ={},
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"]["code"] == "invalid_input"
    assert secret not in captured.err
    assert "Traceback" not in captured.err


def test_cli_requires_named_environment_credentials_before_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "Issues.md"
    exit_code = run(
        [
            "sync",
            "linear",
            "--team-key",
            "ENG",
            "--key-env",
            "MISSING_KEY",
            "--output",
            str(output),
        ],
        environ={},
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.err)["error"]["code"] == "invalid_input"
    assert not output.exists()


class EmptyTransport:
    def __init__(self, response: object = None) -> None:
        self.response = [] if response is None else response

    def request_json(self, method: str, url: str, **kwargs: object) -> object:
        return self.response


class RecordingTransportFactory:
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses = responses or {}

    def __call__(self, **kwargs: object) -> EmptyTransport:
        self.calls.append(kwargs)
        host = next(iter(kwargs["allowed_hosts"]))
        return EmptyTransport(self.responses.get(host, []))


def test_github_cli_resolves_optional_env_token_and_transport_bounds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "Issues.md"
    factory = RecordingTransportFactory()
    exit_code = run(
        [
            "sync",
            "github",
            "--owner",
            "acme",
            "--repo",
            "widget",
            "--token-env",
            "GH_TOKEN",
            "--timeout-seconds",
            "4.5",
            "--output",
            str(output),
        ],
        environ={"GH_TOKEN": "fixture-token"},
        transport_factory=factory,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["issueCount"] == 0
    assert factory.calls == [
        {"allowed_hosts": {"api.github.com"}, "timeout_seconds": 4.5}
    ]


@pytest.mark.parametrize(
    ("provider_args", "environ", "host", "response"),
    [
        (
            [
                "jira",
                "--base-url",
                "https://acme.atlassian.net",
                "--jql",
                "project = ENG",
            ],
            {"JIRA_EMAIL": "operator@example.com", "JIRA_API_TOKEN": "fixture"},
            "acme.atlassian.net",
            {"issues": [], "isLast": True},
        ),
        (
            ["linear", "--team-key", "ENG"],
            {"LINEAR_API_KEY": "fixture"},
            "api.linear.app",
            {
                "data": {
                    "issues": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        ),
    ],
)
def test_remote_cli_composes_jira_and_linear_without_live_io(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    provider_args: list[str],
    environ: dict[str, str],
    host: str,
    response: object,
) -> None:
    output = tmp_path / f"{provider_args[0]}.md"
    factory = RecordingTransportFactory({host: response})
    exit_code = run(
        ["sync", *provider_args, "--output", str(output)],
        environ=environ,
        transport_factory=factory,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["source"] == provider_args[0]
    assert factory.calls[0]["allowed_hosts"] == {host}


def test_cli_converts_source_and_output_failures_to_sanitized_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.md"
    output = tmp_path / "generated.md"
    exit_code = run(
        [
            "sync",
            "issues-md",
            "--input",
            str(missing),
            "--output",
            str(output),
        ],
        environ={},
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    error = json.loads(captured.err)["error"]
    assert error["code"] == "source_error"
    assert "Traceback" not in captured.err


def test_cli_does_not_echo_malformed_url_fragments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sensitive_fragment = "never-echo-url-fragment"
    exit_code = run(
        [
            "sync",
            "jira",
            "--base-url",
            f"https://acme.atlassian.net:{sensitive_fragment}",
            "--jql",
            "project = ENG",
            "--output",
            str(tmp_path / "out.md"),
        ],
        environ={"JIRA_EMAIL": "operator@example.com", "JIRA_API_TOKEN": "fixture"},
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert sensitive_fragment not in captured.err
