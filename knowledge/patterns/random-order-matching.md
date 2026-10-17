---
id: random-order-matching
name: Random or one-at-a-time matching of work to resources
stage: mid
cost: 20-60 min
risk: mid
signature: a digest contains ORDER BY RAND(), or a matcher picks one item per interval
sources:
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: マッチング、距離 400、ランダム性の除去)
  - https://zenn.dev/layerx/articles/3bd55b77e047c4 (ISUCON14 LayerX: interval 短縮 3742→4169, 複数 rides 4169→4981)
---
## Symptom

A background matcher assigns one waiting ride to a random active chair every
500ms (`ORDER BY RAND() LIMIT 1`). Distant chairs are chosen, rides wait,
and the score (ride completions, user satisfaction) stalls regardless of
request throughput. The 解説 calls the benchmark's satisfaction terms the
real score driver from the middle of the contest on.

## Hypothesis template

Matching throughput and quality bound the score: processing all waiting
rides per tick and choosing the nearest free chair (skipping pairs farther
than a threshold) completes more rides per minute than random single
assignment.

## Change template

In order of cost:
1. Shorten the matcher interval (ISUCON14: `ISUCON_MATCHING_INTERVAL`,
   cheap, allowed by the manual) and process every waiting ride per call.
2. Replace `ORDER BY RAND()` by nearest-free-chair with a distance cutoff
   (the 解説's sample uses 400) and no randomness.
3. Keep free chairs and waiting rides in memory; assignment becomes a loop.
4. Only if the above saturate: bipartite matching / min-cost flow per tick.

## Checklist

- Running the matcher on more than one host double-assigns chairs; ISUCON14
  解説 names this as the cause of multi-host benchmark failures. One matcher,
  or a transaction that claims the ride.
- Removing randomness also removes score variance; expect the baseline noise
  to drop after this change (re-measure the baseline).
- Changing the interval is a configuration change: deploy it through the
  overlay or the env file, and record it in the manifest.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- ISUCON14 解説: teams reached the top ranks by raising the matching frequency
  alone; the greedy nearest-chair solution was the intended one.
- LayerX: interval 3742→4169, several rides per request 4169→4981, nearest
  chair later in the day (big jump, score not isolated).
