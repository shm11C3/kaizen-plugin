---
id: heavy-aggregate-query
name: Aggregate recomputed on every read
stage: mid
cost: 20-45 min
risk: mid
signature: a SELECT with SUM/COUNT/GROUP BY or ORDER BY ... LIMIT averages >=10ms
sources:
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: owner/chairs の総走行距離、観光名所)
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: 統計情報の N+1、計算結果を保持するテーブル)
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: billing は大会終了時に 1 回計算して保存)
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
   first; LayerX 3282→3742).
2. Maintain a derived table (`chair_total_distance`, latest location per
   chair) updated in the same transaction as the write; read from it.
3. Compute once at the event that freezes the value (ISUCON12 billing at
   `finish`), store it, never recompute.

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

## Notes from write-ups

- ISUCON14 解説 recommends a per-chair table with latest position and total
  distance, maintained by UPSERT; LayerX did the DB-side cache mid-contest.
- ISUCON13: user and livestream statistics were N+1 aggregates; the 解説
  suggests one query or a results table.
