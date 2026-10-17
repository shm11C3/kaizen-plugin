---
name: plan
description: "Choose experiments by current scoring impact, evidence, uncertainty and total time. Use after setup, after each decision, when predictions fail or strategy signals fire. Maintains .kaizen/plan.md and reconsiders mechanisms before repeating small tweaks."
---

# Plan

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup). Teams apply the reservation boundary
in the team skill; workers read shared artifacts, the integrator owns the plan.
Read `$K/team/docs/STRATEGY.md` for the decision and allocation procedure.

Start from a comparable baseline and observations. The objective is the final
valid score within the deadline. Experiment count and agent activity are costs
and diagnostic metrics, not success measures.

```bash
$K/scripts/knowledge.sh plan [<observe dump>]
$K/scripts/strategy.sh status
$K/scripts/strategy.sh review       # prints a template; no deployment or approval gate
```

The generated order is a seed from signatures and historical outcomes. History
is not a calibrated success probability and different problems have different
scoring paths. Current evidence and human strategy determine the final order.
Previous choices, manually added options and Notes survive regeneration; every
retained choice must be revalidated against the current stable/bundle.

For each serious option, fill:

1. **scoring path**: direct score term and manual reference, indirect resource
   relief with observed contention, or unknown. Unknown starts with investigation.
2. **expected score impact** and **uncertainty**: explain the causal chain and
   observations. A faster query alone does not establish a score gain. Distinguish
   time doing work from time waiting for a lock, connection or another request.
   Use ranges or qualitative estimates; do not invent precise probabilities.
3. **total minutes**: implementation, checks/tests, compilation/linking, queue,
   deployment, fresh samples, recovery (including its rebuild);
   include a final stable/restart verification reserve.
4. **dependencies**: prerequisites, conflicts, current base. An enabler with no
   measured gain is not automatically adopted; compare a coherent combination
   as its own candidate when appropriate, with human judgment for material risk.
5. **disproof**, **stop when**, **order**, **reason**: what outcome distinguishes
   this explanation from another and what ends the experiment.

Add an observation-derived hypothesis even if no corpus signature matches.
Consider a structural alternative when bounded tweaks cannot explain the cost;
roles remain dynamic, and a safe comparison can proceed before human adoption.
Follow the highest justified order, not a fixed index/cache/config recipe.

After every record, update outcomes, prediction errors and allocation in plan.md.
After promotion, observe again: the limiting resource may have moved. If history
flags repeated hypotheses, A→B→A parameter changes, or no rule-verified promotion
for 3 experiments / 30 experiment-minutes, complete a brief strategy review at a
stable boundary. These are advisory defaults, not proof that the strategy failed.
Explain new evidence before retrying. Noise, missing samples and unexplained
errors remain AI investigation; only concrete risk/tradeoff choices need humans.

The existing Stop hook asks for an updated plan after a record. Do not add a new
meeting, approval or extra model call for every task. Preserve the human's order,
exclusions, deadline and stop instructions.

When tests or coupling block a promising candidate, use prepare-tests/refactor
and `team/docs/PHASES.md`. Include preparation in total time, name the dependent
candidate and stop condition, and retain final verification time. Prefer existing
tools under `team/docs/TOOLS.md` to custom instrumentation.
For Rust, use measured build/recovery times under `team/docs/RUST_BUILD.md`;
do not equate a warm local no-change build with the actual deployment path.
