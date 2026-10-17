---
name: setup
description: Prepare a repository and its servers for the kaizen loop. Use at the start of a contest or practice session, or whenever .kaizen/config.sh is missing, hosts changed, or the stable revision must be re-pinned. Writes .kaizen/config.sh from a preset or the day's manual, pins STABLE_REV, deploys it, runs the recovery drill, and takes the first baseline.
---

# Setup

Scripts live at `<this skill's base directory>/../../scripts/`. Set `K` to
that plugin root once per session and run every script as `$K/scripts/<name>.sh`
from the repository root (the project is the current directory).

## 1. The repository

The project is a git repository that holds the application directories the
servers run (for ISUCON: `go/`, `sql/`, and `etc/` for configuration). If
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
  `BENCH_MODE=manual` (the portal runs the benchmark). Keep the manual's URL
  in a comment next to each value taken from it.
- Add `.kaizen/bench.lock` and `.kaizen/state.env` to `.gitignore`; commit
  `.kaizen/config.sh` and the experiment records.

Read the manual once for the rules the loop must not break and list them in
`.kaizen/RULES.md`: endpoints whose response shape is fixed, files or
services that must not change, what `/initialize` must restore, whether
external services or AI APIs may be called from the servers, and the time
limit of the initialize endpoint. The hypothesize skill reads this file.

## 3. Pin stable and prove recovery

```bash
cd <project>
printf 'STABLE_REV=%s\n' "$(git rev-parse main)" > .kaizen/state.env
$K/scripts/deploy.sh main            # pushes, builds, restarts, verifies every host
$K/scripts/recover.sh                # the drill: stable must be restorable before any candidate
```

If deploy fails, fix config.sh (paths, commands, SSH) until `verify.sh main`
reports every host matching; do not start experiments on a target you cannot
restore.

## 4. First baseline

```bash
$K/scripts/observe.sh reset
$K/scripts/bench.sh baseline          # ssh mode
$K/scripts/bench.sh baseline --result 'pass=true score=1234 errors=none'   # manual mode, after the portal run
$K/scripts/observe.sh dump baseline
$K/scripts/bench.sh baseline-2
```

Two samples show the noise; three when the two differ by more than
`MIN_IMPROVEMENT_BP`. Commit `.kaizen/` (config, RULES, samples, dump) on
`main`, then `$K/scripts/stable.sh repin`: the commit moved `main` past
STABLE_REV without changing what the servers run, and repin moves
STABLE_REV (and the baseline samples' key) to it after verifying the
hosts still match. Report `$K/scripts/status.sh` to the human and stop:
the loop starts with the observe skill.
