---
name: hypothesize
description: Turn an observation into one testable hypothesis and open an experiment for it. Use after observe, or when the human proposes a change: writes the Candidate Manifest (hypothesis, cited evidence, allowed change, expected effect) that deploy.sh requires before any candidate reaches a server.
---

# Hypothesize

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run from
the repository root.

One experiment tests one mechanism. "Add indexes" is one hypothesis;
"add indexes and cache the user lookup" is two experiments, because a score
change could not be attributed to either.

## Pick

From the observation file, choose the single largest cost whose fix you can
name in one sentence, in this order of preference: missing index; query
inside a loop (N+1); work repeated on every request that a cache or a
precomputed column removes; a configuration limit (fsync on every commit,
connection limits, worker counts); polling or matching intervals the manual
allows to change. Check `.kaizen/log.md` so a rejected hypothesis is not
retried unchanged, and `.kaizen/RULES.md` so the change stays inside the
rules.

## Open

```bash
$K/scripts/experiment.sh new <slug>       # branch exp/NNN-<slug> from stable, manifest template
```

Fill `.kaizen/experiments/NNN-<slug>/manifest.json` completely:

- `hypothesisId`: short stable id (`idx-rides-chair`), reused if retried later.
- `hypothesis`: what is slow, why, and what change removes it.
- `observations[0]`: `summary` with the numbers, `artifact` = the
  observe-*.txt path (relative to the repository).
- `allowedChanges`: every file the change touches, with `changeKind` and why.
- `changeSummary`, `expectedEffect`: which endpoint or query gets faster and
  the score direction. If you cannot say which, the hypothesis is not ready.

deploy.sh refuses a candidate while `hypothesis`, `observations[0].artifact`
or `expectedEffect` is empty. Then continue with the experiment skill.
