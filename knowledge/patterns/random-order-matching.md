---
id: random-order-matching
name: Random or one-at-a-time matching of work to resources
stage: mid
cost: 20-60 min
risk: mid
signature: a digest contains ORDER BY RAND(), or a matcher picks one item per interval
sources:
  - https://isucon.net/archives/58869617.html
  - https://zenn.dev/layerx/articles/3bd55b77e047c4
---
## Symptom

A background matcher assigns one waiting ride to a random active chair every
500ms (`ORDER BY RAND() LIMIT 1`). Distant chairs are chosen, rides wait,
and the score (ride completions, user satisfaction) stalls regardless of
request throughput.

## Hypothesis template

Matching throughput and quality bound the score: processing all waiting
rides per tick and choosing the nearest free chair (skipping pairs farther
than a distance threshold) completes more rides per minute than random single
assignment.

## Change template

In order of cost:
1. Shorten the matcher interval (ISUCON14: `ISUCON_MATCHING_INTERVAL`,
   cheap, allowed by the manual) and process every waiting ride per call.
2. Replace `ORDER BY RAND()` by nearest-free-chair with a distance cutoff
   and no randomness; find the threshold by measurement.
3. Keep free chairs and waiting rides in memory; assignment becomes a loop.
4. Only if the above saturate: bipartite matching / min-cost flow per tick.

## Checklist

- Running the matcher on more than one host double-assigns chairs and fails
  the benchmark. One matcher, or a transaction that claims the ride.
- Removing randomness also removes score variance; expect the baseline noise
  to drop after this change (re-measure the baseline).
- Changing the interval is a configuration change: deploy it through the
  overlay or the env file, and record it in the manifest.
- 003-matching-interval (isucon14): interval 0.5s -> 0.1s with the random
  picker unchanged was rejected (median -5%); the picker retries up to ten
  random chairs per call and most are busy, so more calls mostly add DB
  load. Fix the picker before the interval.

- 004-nearest-chair-matching (isucon14): a chair counts as free only once
  it has been *notified* of its last ride's completion (every status row
  has `chair_sent_at`), not when the ride has an evaluation. Using
  `rides.evaluation IS NULL` assigned a new ride too early and the
  benchmark failed with error 15 after 12 seconds. Keep the original
  "all six statuses sent" condition when rewriting the free-chair query.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon14 | 003-matching-interval | 3627/4119 | 3441/3934 | -5% | 2+2 | 2 | reject | reject | map[25:13]; map[25:15] |
| isucon14 | 004-nearest-chair-matching | 3627/4119 | - | - | 2+0 | 1 | reject | reject | map[15:1] |
