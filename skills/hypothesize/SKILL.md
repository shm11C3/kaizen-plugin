---
name: hypothesize
description: "Turn an observation into one testable hypothesis and open an experiment for it. Use after observe, or when the human proposes a change: writes the Candidate Manifest (hypothesis, cited evidence, allowed change, expected effect) that deploy.sh requires before any candidate reaches a server."
---

# Hypothesize

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup).

One experiment tests one mechanism. "Index one measured access pattern" is one hypothesis;
"add indexes and cache the user lookup" is two experiments, because a score
change could not be attributed to either.

## Plan first

If `.kaizen/plan.md` exists, take the top item not yet done and keep its
reason; if it does not exist, run the plan skill before hypothesizing.

## Match

```bash
$K/scripts/knowledge.sh match <observe-*.txt>     # patterns the evidence supports, ranked, with measured history
```

Read the matching pattern files (`$K/knowledge/patterns/<id>.md`): the
Measured table says what the pattern paid before and how often it failed,
the Checklist what to verify. The matcher proposes; the dump decides. If
the largest cost in the dump matches nothing, that is the hypothesis to
write, with a new `patternId`; do not bend the observation to fit a pattern.

## Pick

Choose the highest justified item in the plan using the current scoring path,
observed limiting resource, uncertainty and total verification time. There is no
fixed preference for indexes, caches or configuration changes. A cheap local
change may have little scoring impact, and expensive structural work needs a
bounded comparison and recovery plan.

Check `.kaizen/log.md` and `strategy.sh status` before repeating a mechanism.
Record what new evidence or assumption makes a retry informative. If the main
cost might be waiting rather than processing, distinguish the two before fixing
SQL/CPU. Read `.kaizen/RULES.md`; the change must stay within the rules.

## Open

```bash
$K/scripts/experiment.sh new <slug>       # branch exp/NNN-<slug> from stable, manifest template
```

In a team, only the reservation holder opens this experiment through
`control.py target --agent SESSION --token TOKEN experiment new SLUG --github-user GITHUB_LOGIN`.
Its branch is `<github-login>/exp/NNN-SLUG`. Workers prepare their submitted
source on `<github-login>/T-0001-summary`; check the current Discord discussions
and shared ledger before choosing the hypothesis.

Fill `.kaizen/experiments/NNN-<slug>/manifest.json` completely:

- `patternId`: the knowledge pattern id (`missing-secondary-index`), or a new
  id when none fits; ingest files the result under it.
- `hypothesisId`: short stable id (`idx-rides-chair`), reused if retried later.
- `hypothesis`: what is slow, why, and what change removes it.
- `observations[0]`: `summary` with the numbers, `artifact` = the
  observe-*.txt path (relative to the repository).
- `allowedChanges`: every file the change touches, with `changeKind` and why.
- `strategy`: mechanism; scoringPath (direct/indirect/unknown) and scoringEvidence;
  expectedImpact and uncertainty; estimatedMinutes including queue, samples and
  recovery; disproof and dependsOn. For parameter experiments, put the actual
  setting(s) in `parameters` and reuse hypothesisId so oscillation can be found.
  These fields aid planning and review; empty historical fields are not evidence.
- `changeSummary`, `expectedEffect`: which endpoint or query gets faster and
  the score direction. If you cannot say which, the hypothesis is not ready.

deploy.sh refuses a candidate while `hypothesis`, `observations[0].artifact`
or `expectedEffect` is empty. Then continue with the experiment skill.
