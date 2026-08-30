# Draindeck

Draindeck is a local Windows tool that works through an `Issues.md` backlog.
For each issue, it asks a coding agent to make the change, runs your validation
commands, gets an independent review, and commits only approved work.

## Requirements

- Windows, Python 3.12+, and Git
- Claude Code for implementation
- Ollama with a Qwen model for review

## Install

```powershell
git clone https://github.com/AdityaVasireddy/draindeck.git
cd draindeck
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item config.example.yaml config.local.yaml
```

Edit `config.local.yaml` to set your target repository, branch, validation
command, and Ollama/Qwen settings. Keep this local file out of Git.

## Add issues

Create an `Issues.md` file in the target repository:

```md
## 1: Add a health check

Create a simple health endpoint.

### Acceptance
- The endpoint returns HTTP 200.
- Tests pass.
```

## Run

Check your configuration first:

```powershell
.\.venv\Scripts\python.exe -m runtime.main check-config config.local.yaml
```

Then run Draindeck:

```powershell
.\.venv\Scripts\python.exe -m runtime.main run --config config.local.yaml
```

Use this command after an interrupted run to recover safely without starting
new work:

```powershell
.\.venv\Scripts\python.exe -m runtime.main recover --config config.local.yaml
```

## Import issues (optional)

Generate a local `Issues.md` from another file, GitHub, Jira Cloud, or Linear:

```powershell
draindeck-intake sync issues-md --input C:\source\Issues.md --output C:\target\Issues.md
draindeck-intake sync github --owner OWNER --repo REPO --output C:\target\Issues.md
draindeck-intake sync jira --base-url https://SITE.atlassian.net --jql "project = KEY" --output C:\target\Issues.md
draindeck-intake sync linear --team-key ENG --output C:\target\Issues.md
```

Credentials come from environment variables: `GITHUB_TOKEN`, `JIRA_EMAIL` +
`JIRA_API_TOKEN`, or `LINEAR_API_KEY`.

## Dashboard (optional)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dashboard]"
.\.venv\Scripts\draindeck-dashboard.exe --config dashboard.local.yaml
```

Open <http://127.0.0.1:8420/>.

## Important

Draindeck can modify target repositories and make commits. Start with a test
repository, review `config.local.yaml`, and explicitly authorize real runs.

For full architecture, safety, and provider details, see `docs/` and
`docs/29-draindeck-intake.md`.
