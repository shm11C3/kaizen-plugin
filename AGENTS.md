# kaizen plugin

An ISUCON improvement loop. The procedures are in `skills/<name>/SKILL.md`
(setup, observe, hypothesize, experiment, recover, status); the mechanics are
in `scripts/`; `hooks/guard.py` refuses what bypasses them.

Rules that hold for any agent using this repository against a target:

- Every deploy goes through `scripts/deploy.sh <ref>`, every benchmark
  through `scripts/bench.sh <label>`, every return to stable through
  `scripts/recover.sh`. Nothing else touches the servers' application
  directories, configuration, or services.
- One experiment tests one hypothesis, opened with `scripts/experiment.sh new`
  and closed with `scripts/experiment.sh record`. The manifest cites an
  observation file before any candidate is deployed.
- `decision.json`, `record.json`, `bench-*.json`, `baseline/`, and
  `state.env` are written only by the scripts. Disagreeing with the rule is
  done with `record --override <decision> <reason>`, never by editing.
- A correctness failure is never promoted.
- When the human says stop: finish the running script, recover stable unless
  the last decision was promote, record, report.

Codex: there is no hook adapter yet; follow the rules above by hand and run
`tests/run.sh` after changing a script.

Prepare or stop sandbox EC2 lanes with `scripts/team/ec2_lanes.py` and
`team/docs/PARALLEL_QUALITY.md` only at an idle boundary. Keep its operation
state and the shared team ledger; exclude official/control resource IDs.
Provisioning does not replace environment registration, target.py reservations,
deployment scripts, recovery drills or lane-specific baseline measurements.
To advance an idle sandbox to an adopted competition revision, use the owned
`target.py stable-sync --record <official experiment record.json>` action.
Never fake a sandbox promotion or edit stable state to import official code.
If synchronization remains pending, use its owned `--rollback` action before
other target operations. New source requires a new sandbox baseline.

For a shared competition, start with `skills/team/SKILL.md` and follow
`team/POLICY.md` and `team/docs/DISCORD.md`. Each member uses an independent
session, reads current Discord decisions and coordinates through the shared ledger.
Adopt evidence-backed, recoverable improvements within the agreed limits even
when structural or large; classify human review under `team/POLICY.md`, not by size.
Use the member's GitHub login as the branch prefix; keep session IDs distinct.
Team procedures, coordination scripts, infrastructure and
templates belong to this plugin; the competition repository holds source and
minimal bootstrap guidance only. Run
`python3 -m unittest discover -s tests -p test_team.py -v` after changing team mechanics.

Within each Discord-facing main session, follow `team/docs/PIPELINE.md`.
Use native subagents when independent preparation can overlap: initially one
implementation plus one next-candidate investigation per main session, with
dynamic roles and existing shared READY backpressure. The candidate writer
owns implementation through related checks and READY artifacts under
`skills/prepare-candidate/SKILL.md`; keep one mutable owner per worktree.
The main session owns task identity and Discord coordination. Optional
`task-stage` observations and read-only `pipeline-status` expose recorded
boundaries without adding approvals, scheduling or quality proof. Include
preparation, handoff, measurement, repair, final verification and cleanup in
the remaining budget; an early source-freeze estimate alone is not a stop rule.

Experiment selection follows `team/docs/STRATEGY.md` and the plan skill.
Optimize the final valid score, not experiment count. Strategy notifications
are advisory AI investigation triggers; they never waive correctness or add
routine human approval. Preserve the human's strategy and stop instructions.
Use `team/docs/COMPARISON.md` before claiming an advantage from the plugin.

For repeated operations, follow `skills/improve-workflow/SKILL.md` and
`team/docs/WORKFLOW.md`: practice refines reusable skills while keeping
problem-specific procedures as knowledge; competition can also specialize skills.
Integrate tested tools into private plugin main and roll out at an idle boundary.
Keep competition main separate. Read `team/docs/REGULATIONS.md`
before choosing manual operations or isolated parallel validation environments.

Follow `team/docs/VALIDATION.md`: run the existing test suite and formatter/lint
suite by default, then adjust only checks measured to be costly. Record seconds,
cold/warm and duplicate-build costs, and any omitted scope/reason. New coverage,
race checks and independent or LLM contract review are separate risk-driven
choices, not automatic additions. The real official benchmark supplies performance
and checker correctness evidence for adoption. Known correctness
failures and open quality holds still require repair; a benchmark pass cannot
waive them. Follow `team/docs/LINT.md`, retain diagnostic
dispositions and untested scope, and do not block submission on advisory style.
Go and Rust use existing tools under `team/docs/TOOLS.md`.
Setup registers existing suites in resident settings.checks; the integrator
runs configured checks on the actual candidate before deploy with check.py.
Empty checks are unconfigured/not run, never a PASS. Preserve blocking failures
through quality hold/recovery and keep advisory results explicit.
Optional contract tests and bounded preparation/refactor phases follow
`team/docs/PHASES.md`, `skills/prepare-tests/SKILL.md` and `skills/refactor/SKILL.md`.
Record preparation time and the dependent improvement. Costly collection uses
observe start/stop; observed samples never establish adoption.
