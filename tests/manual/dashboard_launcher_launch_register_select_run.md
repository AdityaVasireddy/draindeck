# Manual proof: launcher launch -> register -> select -> Run

Status: opt-in manual proof, not a CI substitute (docs/32 L-14). This is
the only place the end-to-end launcher path is exercised against a real
process tree and a real Git repository; every decision inside the
launcher itself is covered by automated tests in `tests/unit`,
`tests/dashboard`, and `tests/integration` (see
`docs/plans/cross-platform-dashboard-launcher-failing-tests.md`).

## Prerequisites

- A supported host with dependency setup already completed (Python
  findable, and either the fast path's `.venv` already present, or
  willingness to consent to the cold-install prompts).
- `git` on PATH, used only to build the disposable fixture repository.
- Nothing already listening on the Dashboard's configured port
  (default `127.0.0.1:8420`).

## 1. Build a disposable Git fixture repository

Use a scratch directory outside the Draindeck repository itself so
nothing here is mistaken for tracked project state:

```sh
mkdir -p /tmp/draindeck-launcher-fixture && cd /tmp/draindeck-launcher-fixture
git init -q
git config user.email "fixture@example.com"
git config user.name "Fixture"
cat > Issues.md <<'EOF'
# Issues

## ISSUE-1: Add a NOTES.md placeholder file
STATUS: NEW

Create an empty `NOTES.md` file at the repository root.
EOF
git add Issues.md
git commit -q -m "seed fixture issue"
```

`Issues.md`'s `STATUS` field is decorative input text only (CLAUDE.md);
the actual state this proof observes is `events.jsonl` under the fixture
repository's `.draindeck/` directory, written by the controlled safe
executor below.

## 2. Launch

From the Draindeck repository root, run the entry point for your OS:

- Windows: double-click `Start-DraindeckDashboard.cmd`, or run it from a
  shell.
- macOS: double-click `Start-DraindeckDashboard.command` in Finder, or
  run it from a shell.
- Linux: `./start-draindeck-dashboard.sh`

Observe and record:

- Whether any install-consent prompt appeared, exactly what it listed as
  missing (source + command), and what you answered.
- Whether the browser opened automatically, and how long that took
  (compare against the 180s fast-path budget when the environment was
  already fully set up; a cold install has no time promise, only live
  progress).
- The visible Dashboard-ready / Run-ready indicators in the opened page
  (they must be shown independently -- Dashboard can be ready while Run
  is not, per docs/32 L-10).

## 3. Register the fixture repository

In the opened Dashboard UI, register the fixture repository from step 1
(its absolute path) through the Repositories page's registration form.
This calls `POST /api/repositories`, which internally routes any target
configuration write through `runtime.init.service.apply_target_configuration`
-- never through the launcher.

## 4. Select one issue and Run it

Open the fixture repository's Issues view, select `ISSUE-1`, and choose
**Run selected**. This calls `POST /api/repositories/{repo_id}/run-commands`,
which enqueues exactly one run-command; the queue-drain scheduler claims
it and spawns exactly one Draindeck runtime process via the safe launcher
pattern (`run_launcher.py`, argv-only, `shell=False`) — the same
committed pattern `observer_client.py` and this Dashboard launcher both
use.

## Expected evidence

Record, with exact values:

1. **One queue command.** `GET /api/repositories/{repo_id}/run-commands`
   shows exactly one command for `ISSUE-1`, progressing
   `CLAIMED -> LAUNCHED -> COMPLETED` (or `ABNORMAL_EXIT`/
   `LAUNCH_FAILED` if the fixture's environment can't actually complete a
   real resolution attempt -- this proof is about the launcher's process
   lifecycle, not the runtime's resolution quality).
2. **One Draindeck runtime process.** Exactly one child process was
   spawned for this command (inspect via OS process list at the moment
   the command is `LAUNCHED`, or the Dashboard's own diagnostic byte
   counts in the run-command detail, which only accrue for a single
   live child).
3. **The expected `events.jsonl` lifecycle.** Under the fixture
   repository's `.draindeck/` state directory, `events.jsonl` contains
   the expected sequence of events for one issue attempt (per
   `docs/03-state-machine-and-event-schema.md`) -- never a duplicated or
   double-committed attempt, even if the Dashboard or launcher was
   restarted mid-run.

## 5. Stop and clean up

Use the Dashboard's stop/status affordance (or re-run the entry point,
which reuses the healthy launcher-owned process rather than starting a
duplicate). Confirm stopping only ever targets a PID this launcher can
prove it owns via the recorded instance token and
`GET /api/launcher/identity` (docs/32 L-13) -- record the exact PID and
token compared.

Delete the scratch fixture directory once you're done; it is disposable
and was never part of the tracked repository.
