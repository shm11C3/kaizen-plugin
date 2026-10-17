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

For a shared competition, start with `skills/team/SKILL.md` and follow
`team/POLICY.md`. Team procedures, coordination scripts, infrastructure and
templates belong to this plugin; the competition repository holds source and
minimal bootstrap guidance only. Run
`python3 -m unittest discover -s tests -p test_team.py -v` after changing team mechanics.

Experiment selection follows `team/docs/STRATEGY.md` and the plan skill.
Optimize the final valid score, not experiment count. Strategy notifications
are advisory AI investigation triggers; they never waive correctness or add
routine human approval. Preserve the human's strategy and stop instructions.
Use `team/docs/COMPARISON.md` before claiming an advantage from the plugin.
