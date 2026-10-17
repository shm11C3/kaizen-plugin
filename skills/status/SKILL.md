---
name: status
description: "Show where the improvement loop stands: stable and deployed revisions, open experiment and its samples, baseline, budget, and the log of closed experiments. Use when resuming, before deciding what to do next, or when the human asks how it is going."
---

# Status

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup).

```bash
$K/scripts/status.sh
cat .kaizen/log.md                       # every closed experiment, one row each
cat .kaizen/experiments/<id>/record.json # full evidence for one experiment
```

Report to the human in four lines: what is deployed and whether it is stable;
the open experiment and its next step (deploy, sample, evaluate, record);
the baseline median and noise; experiments promoted / rejected /
inconclusive so far with the current score versus the first baseline.

Next step by state:

| state | do |
|---|---|
| no config.sh or no STABLE_REV | setup skill |
| revert pending | recover skill |
| open experiment, candidate deployed, no decision | experiment skill, step 3 |
| open experiment, nothing deployed yet | experiment skill, step 1 |
| no open experiment, no fresh observation | observe skill |
| fresh observation | hypothesize skill |
