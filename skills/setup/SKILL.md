---
name: setup
description: "Prepare a repository and its servers for the kaizen loop. Use at the start of a contest or practice session, or whenever .kaizen/config.sh is missing, hosts changed, or the stable revision must be re-pinned. Writes .kaizen/config.sh from a preset or the day's manual, pins STABLE_REV, deploys it, runs the recovery drill, and takes the first baseline."
---

# Setup

Scripts live at `<this skill's base directory>/../../scripts/`. Once per
session set `K` to that plugin root and `export KAIZEN_PROJECT=<absolute path
of the repository>`: every script reads the project from that variable, so a
command run from another directory (or a background job) still targets the
right repository. Run scripts as `$K/scripts/<name>.sh`.

## 1. The repository

The project is a git repository that holds the application directories the
servers run (e.g. `go/` or `rust/`, `sql/`, and `etc/` for configuration). If
the servers hold the only copy, create it: `rsync` the application directory
from the server into the repository, commit it on `main` as the first commit,
and note the commit as the initial stable revision. Never edit on the server.

## 2. config.sh

- Practice on a known past problem: copy `$K/templates/config.sh.example` to
  `.kaizen/config.sh`, keep the preset line, fill hosts and private IPs.
- Contest day: copy `$K/templates/preset.sh.example` to
  `.kaizen/preset.sh`, fill every value from the day's manual and the
  servers (application path, build command, service name, health URL,
  database name, how ids look in URLs), then source it from
  `.kaizen/config.sh` and set `APP_HOSTS` to every server, `DB_HOST`, and
  the allowed `BENCH_MODE` from the day's manual (`manual` when portal result
  handoff is required). Keep the manual's URL
  in a comment next to each value taken from it.
- Everything under `.kaizen/` except `config.sh`, `preset.sh` and `RULES.md`
  stays out of git (`experiment.sh new` writes `.kaizen/.gitignore`); the
  durable copy of every record is the plugin's `knowledge/records/`. Commit
  `.kaizen/config.sh` with the code.

Read the manual once for the rules the loop must not break and list them in
`.kaizen/RULES.md`: endpoints whose response shape is fixed, files or
services that must not change, what `/initialize` must restore, whether
external services or AI APIs may be called from the servers, and the time
limit of the initialize endpoint. The hypothesize skill reads this file.

Plugin count caps default to 0 for MAX_BENCH_PER_EXP, MAX_BENCH_TOTAL,
MAX_BENCH_PER_HOUR and MAX_EXP_PER_HOUR. Positive configured quotas remain
explicit limits and count every physical attempt, including missing results
and recovery. Existing configs are not silently migrated to 0. Choose changes
only at an idle boundary, keep official limits and the deadline, and finish
active commands/experiments with their original pinned core. The default
RECOVERY_BENCH_RESERVE=1 applies only to finite applicable caps; MAX_EXP_MINUTES=30
and quality/sample rules remain. A quota-only change leaves stable-bundle
comparison identity intact, but registered team environments hash raw config.sh:
re-register through the existing path while idle rather than weakening identity
guards. See `../../team/docs/VALIDATION.md`.

For a resident integrator, register the application's existing test and
formatter/lint suites in settings.checks using `../../README.md#candidate-checks`.
Each check has a project-relative cwd, command argv, timeout_seconds and optional
gofmt/cargo diagnostics. Adapt paths, flags and features to the actual project.
Style-only formatter checks may declare advisory=true; retain raw failures
without relabeling them PASS. Test/correctness checks remain blocking by default.
The service runs configured checks on its composed candidate SHA before deploy;
checks=[] remains unconfigured/not run in the ledger, never a synthetic PASS.

## 2b. Quiet hosts

A fresh AMI runs unattended-upgrades on first boot (ISUCON12 practice: it
replaced mysql-server and the docker CLI and ate half a core for 25
minutes, invalidating every sample). Before the first baseline, on every
host:

```bash
ssh <host> 'sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades; sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer; while pgrep -x unattended-upgr >/dev/null || pgrep -x dpkg >/dev/null; do sleep 5; done; uptime'
```

Keep `BENCH_PRECHECK_CMD` in the preset so a sample is refused while any
package job runs. A host that unattended-upgrades already touched keeps
the new packages across a stop/start: after the reboot check that the
application service is up (`systemctl is-active <service>`) before
`deploy.sh`; on isu12 the upgraded docker daemon refused the old compose
plugin until the unit got `DOCKER_API_VERSION` (shipped as an `etc/`
overlay), and the image could not rebuild until its apt sources pointed at
archive.debian.org. On contest day the servers are the organisers'; read
the manual before touching timers.

## 3. Pin stable and prove recovery

```bash
cd <project>
$K/scripts/stable.sh initialize main
```

Run this once on an uninitialized target while holding the setup reservation.
It pins the committed revision, deploys it, runs the configured RECOVERY_CMD to
initialize resources, captures their identity, and proves recovery. It refuses an
already deployed target and never resets an existing experiment or baseline.
Retain the original server snapshot before initialization. After a partial
failure, inspect the recorded state and complete deployment/capture/recovery
through the existing scripts; do not clear the state to rerun initialization.

If deploy fails, fix config.sh (paths, commands, SSH) until `verify.sh main`
reports every host matching; do not start experiments on a target you cannot
restore.

Configure RESOURCE_FINGERPRINT_CMD/RECOVERY_CMD for schema, indexes, data or
external configuration changes before deploying those candidates. See
`$K/team/docs/RECOVERY.md`. Never capture a failed candidate as stable.
Record original updater/service settings before making authorised changes.
Check the benchmark host as well as app hosts, including Snap refreshes;
BENCH_HOST_PRECHECK_CMD can refuse a busy SSH benchmark host.

## 4. First baseline

```bash
$K/scripts/observe.sh reset
$K/scripts/bench.sh baseline          # ssh mode
$K/scripts/bench.sh baseline --reserve  # manual mode, before the portal run
$K/scripts/bench.sh baseline --result 'pass=true score=1234 errors=none'   # after it ended
$K/scripts/observe.sh dump baseline
$K/scripts/bench.sh baseline-2
```

Manual mode also reserves baseline-2 before the portal starts. All attempts,
including missing results and recovery, count toward any applicable finite
physical-run budgets and the actual time budget.

Two samples show the noise; three when the two differ by more than
`MIN_IMPROVEMENT_BP`. Commit `.kaizen/` (config, RULES, samples, dump) on
`main`, then `$K/scripts/stable.sh repin`: the commit moved `main` past
STABLE_REV without changing what the servers run, and repin moves
STABLE_REV (and the baseline samples' key) to it after verifying the
hosts still match. Report `$K/scripts/status.sh` to the human and stop:
the loop starts with the observe skill.

For the planned Go/Rust choice, fill LOCAL_SYNC_PATHS, BUILD_CMD, binary excludes
and service paths from the actual source layout. Go examples use go build; Rust
uses its application's cargo build --release --locked and correct binary path.
Keep debug/race/instrumented builds out of adoption samples. Use native Go/Rust
checks selected under `../../team/docs/VALIDATION.md`; optional targeted test
preparation follows `../../team/docs/PHASES.md`. Do not assume
the bundled ISUCON14 Go preset configures a different language automatically.
Choose Go/Rust using the tradeoff in `team/docs/RUST_BUILD.md`: measured build/test
and repair cycle time, runtime score, compile-time safety and setup/implementation
cost. AI prepares evidence and a recommendation; material tradeoffs follow the
existing human decision policy. Do not require a lengthy language trial on contest day.
For Rust, preserve target caches across sync,
measure the real deploy/recovery build path, and budget that time before experiments.
