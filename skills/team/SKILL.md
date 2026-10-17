---
name: team
description: "Join or resume an autonomous ISUCON team after cloning the competition repository. Use for Claude or Codex team participation, task discovery and atomic claims, candidate submission, serialized integration and benchmarks, human decisions, or control-host operations. Keeps all shared operating rules and tooling in the installed plugin."
---

# Team

Set `K` to this skill's plugin root (`<skill base directory>/../..`) and
`KAIZEN_PROJECT` to the absolute path of the competition clone. The plugin
installation and the competition clone are separate directories.

## Join

1. Read `$K/team/POLICY.md`, then `$K/team/docs/OPERATIONS.md` and
   `$K/team/docs/RUNBOOK.md` and `$K/team/docs/DISCORD.md`.
   Members use independent sessions on their own PCs and coordinate through
   the configured private Discord. Read shared discussions yourself; another
   session's context and local files are not automatically available.
2. Identify the member's actual GitHub login and choose a unique session ID,
   e.g. `<github-login>-codex-01` or `<github-login>-claude-01`. Read the human's current
   strategy, exclusions, time budget, and stop instructions.
   Record practice/competition mode and consult `../../team/docs/REGULATIONS.md`
   for permitted methods and operator handoffs. For recurring work use
   `../improve-workflow/SKILL.md`: practice refines reusable skills and saves
   problem-specific procedures as knowledge; competition can also specialize skills.
3. Run `python3 "$K/scripts/team/join.py" --project "$KAIZEN_PROJECT" --agent SESSION --provider codex`
   (or `--provider claude`). This checks the clone/Git access, makes a tiny model
   request with no source in an empty directory, checks AWS/SSM and the control
   release, and registers membership. `--model MODEL` is a command-only override.
   `--offline` checks files only and does not mean joined. Use `--host-config`
   explicitly for another environment. Do not start work until `joined: true`.
4. Work autonomously through discovery, task creation/claim, local implementation,
   validation, candidate submission, and the next useful task. Keep source work
   isolated in a branch or worktree. Use the plugin's `team/templates/`.
   Name worker branches `<github-login>/T-0001-summary`. Read current Discord
   decisions and related threads before claims and at work boundaries; post
   verified state changes and artifact references after updating the ledger.
   Check Discord read/write access separately: join.py does not probe it.
   Read `$K/team/docs/STRATEGY.md`; choose work by score impact and evidence.
   Check `control.py queue` at work boundaries. If READY candidates accumulate,
   use investigation/comparison tasks to analyze existing evidence or unblock measurement.
   Automatic task-claim skips implementation when READY reaches its --ready-limit
   (default 2); --id is an intentional exception after checking the queue.
   Use --hypothesis MECHANISM_KEY to avoid duplicate active tasks atomically.
   A local investigation/comparison ends with task-complete and its evidence;
   it does not need a deployment or the integration owner's reservation.

## Integration

Any session may become the integration owner, but only one may hold a given
environment's reservation. Use `env-acquire` through `control.py`, retain it through portal
benchmark execution, adoption or recovery, then verify and release it.

Run shared target actions with:

```bash
python3 "$K/scripts/team/control.py" target --agent SESSION --token TOKEN ACTION ...
```

The remote wrapper and ledger run from the control host's plugin installation;
the competition clone contains no management implementation. Target operations
are disabled until the day's source, rules, preset and recovery drill are ready.
When opening an integration experiment, pass the current operator's login:
`target --agent SESSION --token TOKEN experiment new SLUG --github-user GITHUB_LOGIN`.
The generated branch is `<github-login>/exp/NNN-SLUG`; the shared host's account
or Git commit author is not the member's identity.

When using the existing setup, observe, hypothesize, experiment or recover skills
as a team, apply this skill's ownership boundary first. Workers prepare candidate
changes locally; only the reservation holder operates the control-host experiment.
Before task-ready, follow `../../team/docs/LINT.md` on the submitted commit:
attach lint/test records, durations, tool versions and AI diagnostic dispositions.
The integrator reruns relevant checks when integration changes the tested source.

## Decisions and interruption

Ordinary measured, correct, reversible improvements may be adopted autonomously.
Localized correctness repairs, including bounded row locking, do not require
human judgment merely because they introduce a minor implementation tradeoff;
use the material-impact threshold in `../../team/POLICY.md`.
Escalate ambiguous adoption, broad risky changes, significant tradeoffs, or
competing architectural/strategic options with evidence and a recommendation.
Do safe comparison work first; ask before the risky shared action itself.
Never waive correctness. Restore stable while waiting for human judgment.

Missing samples and incomplete validation are AI work: use NEEDS_MEASUREMENT,
then task-resume. If a measured candidate has correctness errors, new warnings,
timeouts or unknown quality, use task-quality-hold as described below instead of
only task-finish NEEDS_MEASUREMENT or prose notes. Reserve
NEEDS_HUMAN for a concrete value/risk/design choice; task-finish requires
--question. Put the options, evidence and recommendation in --reason/the human
decision template. Do not send unfinished investigation to the human queue.

When evaluation blocks on candidate quality, the reservation holder records:

```bash
python3 "$K/scripts/team/control.py" task-quality-hold --id T-NNNN \
  --agent SESSION --token TOKEN --category timeout \
  --evidence /shared/experiment/decision.json --reason 'observed failure and next investigation'
```

Do this before overwriting the submitted source SHA. Preserve/recover the failed
run through normal experiment scripts. The task owner resumes the held task,
adds a reproducer, repairs and resubmits with task-ready; independent prerequisite
tasks may link to it. Do not replace its immutable failure history with an unrelated
new task. Every task-finish ACCEPTED requires an official promotion record,
passing --record and --tested-sha; submitted changed blobs must remain in that
tested source. Unresolved holds follow matching source across task IDs. For
overlapping file compositions, submit the actual integrated SHA before retesting.
Close a held candidate without promotion using an explicit record --override
inconclusive/reject; this remains available for recovery. Sample shortage alone is remeasurement; known
candidate quality problems require the hold ledger. No routine human approval.
For an unchanged-source retry, explain the newly identified cause, corrected
conditions or discriminating measurement. Do not open fresh experiments merely
to obtain a clean pair; carry unresolved warnings from the same source/conditions
forward, even when later runs happen to be clean. A cherry-pick changes commit
identity; compare worker sources and application trees as well as integrated SHAs.

For isolated parallel validation or a quality-held candidate, read
`../../team/docs/PARALLEL_QUALITY.md`. Keep one shared task DB, register the official
resources before sandboxes, and select the matching environment/configuration.
Use `task-quality-hold` to preserve the original SHA, category and evidence;
the owner resumes investigation and resubmits. Submission is RETEST_PENDING,
not resolution. Only a passing official promotion record resolves the hold.
Use a linked investigation for recurrence after adoption; keep accepted history.

The integrator sets manifest.review=human for human candidates and supplies the
actual --human-decision reference to experiment record as well as task-finish.
Keep changedResources accurate. Capture the stable bundle before experiments;
code-only recovery cannot restore SQL/config state. See team/docs/RECOVERY.md.

Plan fresh baseline and candidate samples within the physical-run budget,
reserving a final recovery slot. For a portal run, target bench LABEL --reserve
comes before starting the portal; retain ownership until --result or --abandon
after confirming the portal run ended. All attempts count, even without a score.

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

## Preparation and tools

Go and Rust use native checks and existing observation tools. Read
`../../team/docs/TOOLS.md` and `../../team/docs/PHASES.md` when preparing tests,
profiling or removing a concrete structural blocker. Tests and analysis run
in independent clones in parallel; target collection still uses the reservation.
Use prepare-tests/refactor skills and record cost and downstream payoff.

One mutable workflow owns each worktree. Parallel comparisons use another
worktree, including within a single session. Wait for pending tests/builds before
switching HEAD or committing their source, and publish immutable commits for
other members instead of editing their clones.
