---
name: experiment
description: "Run one experiment end to end on the open hypothesis: change the code on its branch, commit, deploy, benchmark, evaluate with the fixed rule, record the decision, and leave the servers on stable or on the promoted candidate. Use after hypothesize, or to finish an experiment that was interrupted."
---

# Experiment

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup). `$K/scripts/status.sh` first when resuming.

## 1. Change and commit

On the branch opened by hypothesize (`<github-login>/exp/NNN-<slug>` in a team,
`exp/NNN-<slug>` in standalone practice), make only the change the
manifest allows. Configuration changes go under `etc/` (every host) or
`etc-<host>/` (one host) and deploy with the code. Commit with a message
that states the mechanism. Uncommitted changes never deploy.

## 2. Deploy and measure

```bash
$K/scripts/deploy.sh HEAD                        # all hosts; refuses without a filled manifest
$K/scripts/bench.sh candidate                    # ssh mode
$K/scripts/bench.sh candidate --reserve          # manual: before starting the portal
$K/scripts/bench.sh candidate --result 'pass=true score=1234 errors=none'   # manual mode
```

If deploy fails, read the error, fix on the branch, commit, deploy again.
If the sample fails correctness (`pass=false`), the script sets
REVERT_PENDING: run `$K/scripts/recover.sh`, then evaluate and record a
reject with the error kinds in the reason. Do not patch and retry inside the
same experiment unless the manifest still describes the change; otherwise
record and open a new one.

Take as many candidate samples as the plan header says the baseline spread
needs (two, three or four). Take a second sample (`candidate-2`) when the first is within
`MIN_IMPROVEMENT_BP` of the baseline median or the baseline samples spread
more than that. Physical attempts (including no result and final recovery)
consume MAX_BENCH_PER_EXP, MAX_BENCH_TOTAL and MAX_BENCH_PER_HOUR. The default
RECOVERY_BENCH_RESERVE=1 saves the last slot for stable. Closing an experiment
does not reset its recovery budget. Choose the complete measurement plan first.

Run `evaluate.sh` before deciding whether to sample more. If it says
`inconclusive ... noise not separated` and budget remains, take the extra
candidate sample **while the candidate is still deployed**
(`bench.sh candidate-3`), then `recover.sh` and `bench.sh baseline-3`,
then evaluate again. Recording an inconclusive redeploys stable, so the
other order costs an extra deploy.

## 3. Evaluate and record

```bash
$K/scripts/evaluate.sh                           # decision.json: promote / reject / inconclusive, with reason
$K/scripts/experiment.sh record <reason>         # follows decision.json
$K/scripts/experiment.sh record --override <decision> <reason>   # your call differs; both are recorded
```

The score test promotes only when the candidate median beats the
baseline median by `MIN_IMPROVEMENT_BP` and the worst candidate sample beats
the best baseline sample; correctness failures are rejected whatever the
score. Overriding is allowed and visible: use it when you know something the
rule does not (a planned follow-up that needs this change, a known noisy run)
and say so in the reason. Never override a correctness failure.

The current rule is plugin-rule-v2: at least MIN_SAMPLES fresh samples per
revision, one fixed candidate, the same stable bundle, and verified quality.
Unknown errors, new error types and missing request denominators require AI
investigation. Counts alone do not prove rates got worse. Use --requests in
manual mode or parse_bench_requests in the preset for comparable denominators.
Configured CORRECTNESS_ERROR_TYPES always reject. A human reference cannot
waive unresolved quality or incomparable conditions. A performance override to
promote and any manifest.review=human need --human-decision ACTUAL_REF.
record reruns evaluation to include samples added since the previous decision.

Noisy/incomplete evidence is NEEDS_MEASUREMENT in the team ledger. Resume AI
work or archive it when the budget is exhausted; do not invent a human choice.

`record promote` fast-forwards the stable branch, pins the new STABLE_REV,
and reseeds the baseline from the candidate samples; `record reject` and
`record inconclusive` put stable back on every host. Either way the
experiment directory holds manifest, samples, decision, record and timeline.

## 4. Report

One line to the human: experiment id, scores (baseline -> candidate), rule
decision, final decision, what is deployed now. Commit the experiment
directory and `.kaizen/log.md` on `main`, then `$K/scripts/stable.sh repin`
so STABLE_REV follows the records commit (same deployable trees, hosts
untouched; the next `experiment.sh new` branches from it). Then observe
again if a promotion changed the profile, or hypothesize the next item from
the same observation.

If the human says stop: finish the running script, `recover.sh` unless the
last decision was promote, record the experiment, and report the state.
