---
name: team
description: Join or resume an autonomous ISUCON team after cloning the competition repository. Use for Claude or Codex team participation, task discovery and atomic claims, candidate submission, serialized integration and benchmarks, human decisions, or control-host operations. Keeps all shared operating rules and tooling in the installed plugin.
---

# Team

Set `K` to this skill's plugin root (`<skill base directory>/../..`) and
`KAIZEN_PROJECT` to the absolute path of the competition clone. The plugin
installation and the competition clone are separate directories.

## Join

1. Read `$K/team/POLICY.md`, then `$K/team/docs/OPERATIONS.md` and
   `$K/team/docs/RUNBOOK.md`. These are the shared operational source of truth.
2. Pick a unique session ID, e.g. `a-codex-01`. Read the human's current
   strategy, exclusions, time budget, and stop instructions.
3. Run `python3 "$K/scripts/team/control.py" status`. It uses the plugin's
   `team/environments/competition/control-host.json`; pass `--host-config`
   explicitly for another environment. Verify the AWS account before work.
4. Work autonomously through discovery, task creation/claim, local implementation,
   validation, candidate submission, and the next useful task. Keep source work
   isolated in a branch or worktree. Use the plugin's `team/templates/`.

## Integration

Any session may become the integration owner, but only one may hold the shared
reservation. Use `env-acquire` through `control.py`, retain it through portal
benchmark execution, adoption or recovery, then verify and release it.

Run shared target actions with:

```bash
python3 "$K/scripts/team/control.py" target --agent SESSION --token TOKEN ACTION ...
```

The remote wrapper and ledger run from the control host's plugin installation;
the competition clone contains no management implementation. Target operations
are disabled until the day's source, rules, preset and recovery drill are ready.

When using the existing setup, observe, hypothesize, experiment or recover skills
as a team, apply this skill's ownership boundary first. Workers prepare candidate
changes locally; only the reservation holder operates the control-host experiment.

## Decisions and interruption

Ordinary measured, correct, reversible improvements may be adopted autonomously.
Escalate ambiguous adoption, broad risky changes, significant tradeoffs, or
competing architectural/strategic options with evidence and a recommendation.
Do safe comparison work first; ask before the risky shared action itself.
Never waive correctness. Restore stable while waiting for human judgment.

Reservations have no expiry. Inspect actual processes and target state after a
disconnect; never steal a reservation. Follow the runbook for handoff and freeze.

## Installation and administration

Member installation: `$K/team/docs/ONBOARDING.md`.
Control-host provisioning and deployment records: `$K/team/infra/README.md` and
`$K/team/infra/DEPLOYMENT.md`. Members do not need to create another host.

The plugin does not launch new AI sessions or a Discord Bot. Continue the loop
inside the human-started session and use configured private Discord access for
notifications. The current hook adapter targets Claude Code; do not claim a
Codex hook adapter exists.
