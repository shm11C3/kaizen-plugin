---
name: experiment
description: "Run one experiment end to end on the open hypothesis: change the code on its branch, commit, deploy, benchmark, evaluate with the fixed rule, record the decision, and leave the servers on stable or on the promoted candidate. Use after hypothesize, or to finish an experiment that was interrupted."
---

# Experiment

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup). `$K/scripts/status.sh` first when resuming.
In a team, only the environment reservation holder runs this deployment loop.
Workers use `../prepare-candidate/SKILL.md`; independent next-candidate preparation
continues under `../../team/docs/PIPELINE.md` while this loop waits on target work.
An integration assignment includes composition, related checks on its frozen
actual SHA and the next authorized measurement or recovery action. Continue
through those boundaries without waiting for the parent to start each phase.
Record a real authority/dependency wait when the next action is unavailable;
local integration delegation never grants a target reservation implicitly.

## 1. Change and commit

On the branch opened by hypothesize (`<github-login>/exp/NNN-<slug>` in a team,
`exp/NNN-<slug>` in standalone practice), make only the change the
manifest allows. Configuration changes go under `etc/` (every host) or
`etc-<host>/` (one host) and deploy with the code. Commit with a message
that states the mechanism. Uncommitted changes never deploy.
Before deploying that commit, run existing tests and formatter/lint suites under
`../../team/docs/VALIDATION.md` and `../../team/docs/LINT.md`. Measure elapsed
seconds, cold/warm and build duplication; adjust scope/frequency/parallelism only
for measured costly checks and record omissions/reasons. New coverage, race or
independent/LLM review are separate choices. Resolve known correctness diagnostics;
retain advisory/style dispositions without making them a submission gate. Check
the actual integrated source if composition changed it; no routine human approval.
Reuse recorded results only when their source, scope and conditions still apply.
Designing a test in parallel does not establish that the integrated SHA passed it.

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
more than that. The real official benchmark supplies both performance and
checker correctness evidence; local microbenchmarks are auxiliary. Passing it
does not clear a known local defect or open quality hold, or prove all behavior.
All physical attempts (including no result and final recovery) remain counted.
MAX_BENCH_PER_EXP, MAX_BENCH_TOTAL, MAX_BENCH_PER_HOUR and MAX_EXP_PER_HOUR default
to 0 (no plugin count cap for that scope); positive explicit quotas still apply.
RECOVERY_BENCH_RESERVE=1 reserves recovery room only against applicable finite
caps, across their scopes. It creates no official quota or unlimited-scope cap.
Closing an experiment does not reset its consumed budgets. Preserve official
limits, MAX_EXP_MINUTES and final recovery time; plan informative samples first.

Run `evaluate.sh` before deciding whether to sample more. If it says
`inconclusive ... noise not separated` and budget remains, take the extra
candidate sample **while the candidate is still deployed**
(`bench.sh candidate-3`), then `recover.sh` and `bench.sh baseline-3`,
then evaluate again. Recording an inconclusive redeploys stable, so the
other order costs an extra deploy.

## 3. Evaluate and record

Before recording, make the manifest describe the final tested change and its
hypothesis. If steering changed the experiment's purpose, preserve the original
plan as an artifact and update the pattern, hypothesis, strategy and review
classification with the reason before closing. A score gain from application
changes is not evidence for a scheduling or diagnostic method. Closed records
and proof digests stay immutable; correct later knowledge attribution with an
explicit annotation instead of rewriting the adoption proof.

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
New warnings or correctness uncertainty use the team's quality-hold procedure.
A later clean run, clean final pair or different task ID cannot erase an
unresolved hold. For an input collision, establish the specification and repair
the candidate or reproducer accordingly; never weaken an assertion solely to
make an observed failure pass. Clean unadopted ideas retain their prior record;
retry only with changed load, mechanism or new discriminating evidence, not
same-source score rerolls.

When the rule promotes and quality, comparability and resource recovery are
verified within the agreed objective and limits, adopt without an approval wait,
including structural changes. A secondary-metric tradeoff belongs in the normal
decision reason. Apply `../../team/POLICY.md` before choosing human review; do not
silently clear an existing review=human or bypass its required actual reference.

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
