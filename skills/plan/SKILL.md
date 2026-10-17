---
name: plan
description: Decide the order of experiments from evidence before changing anything, and keep that order current. Use after setup (baseline + observation), after every promote, and whenever the remaining time or budget changes: ranks the matched patterns, adds whether each is on the benchmark's scoring path, and writes the order, reason and stop condition into .kaizen/plan.md.
---

# Plan

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup).

Measure first, then plan, then change: two or three baseline samples, one
observation dump, and the matched patterns are the inputs. Changing code
before this is guessing; 006 and 007 on isucon14 were cheap DB fixes that
could not move the score because the endpoints were not on the scoring
path.

```bash
$K/scripts/knowledge.sh plan [<observe dump>]     # writes .kaizen/plan.md: candidates ranked, columns to fill
```

The priority column is mechanical (evidence strength x past promote rate /
typical minutes). It is a starting order, not the decision. Fill the rest:

1. **scoring path?** Read the manual's scoring section once and write,
   per candidate, whether the endpoint or mechanism it speeds up is counted
   (requests that score, satisfaction terms, tips) or only consumes
   resources. Off-path items go last or out.
2. **order** and **reason**: one line each, citing the dump's numbers
   and, when it exists, the pattern's Measured table.
3. **stop when**: the condition that ends the item (two samples inside the
   noise band; a correctness failure; more than N minutes).
4. Under **Notes**: the remaining time and what you will not attempt.

Then hypothesize from the top item. After every `experiment.sh record`:
mark the item done in plan.md with its outcome; after a promote, observe
again and run `knowledge.sh plan` again, because the bottleneck moved.
The Stop hook refuses to end a turn while an experiment closed after the
plan was last written.

The human may edit plan.md at any time; their order wins.
