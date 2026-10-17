---
id: heavy-aggregate-query
name: Aggregate recomputed on every read
stage: mid
cost: 20-45 min
risk: mid
signature: a SELECT with SUM/COUNT/GROUP BY or ORDER BY ... LIMIT averages >=10ms
sources:
  - https://isucon.net/archives/58869617.html
  - https://isucon.net/archives/58001272.html
  - https://isucon.net/archives/56850281.html
---
## Symptom

A read endpoint computes a total (distance travelled, tips, ranking,
billing) by scanning history rows every time: `GET /api/owner/chairs` sums
all `chair_locations` deltas before filtering by owner. Average latency is
tens to hundreds of milliseconds and grows with the data.

## Hypothesis template

The aggregate changes only when rows are written; keeping it in a table or
in memory updated on write (UPSERT per location insert, compute once at
competition finish) makes the read O(1).

## Change template

1. Cheapest: restrict the scan to the rows actually needed (filter by owner
   first).
2. Maintain a derived table (`chair_total_distance`, latest location per
   chair) updated in the same transaction as the write; read from it.
3. Compute once at the event that freezes the value (a competition's
   finish, a ride's completion), store it, never recompute.

## Checklist

- `/initialize` must rebuild or clear the derived table from the initial
  data, within the initialize time limit.
- Every write path that affects the aggregate must update it; list the
  write endpoints in the manifest's allowedChanges.
- The first read after initialize must not see a stale value from the
  previous benchmark run.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

