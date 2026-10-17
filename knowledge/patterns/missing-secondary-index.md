---
id: missing-secondary-index
name: Missing secondary index on hot lookups
stage: early
cost: 5-15 min
risk: low
signature: a SELECT digest examines >=50x the rows it returns over >=20 calls, or a filtered table has only PRIMARY
sources:
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: ほぼインデックスがなく、約4000点まで)
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: 約3,000点から約10,000点)
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: visit_history のカバリングインデックス)
  - https://zenn.dev/layerx/articles/3bd55b77e047c4 (ISUCON14 LayerX: 599→3282)
---
## Symptom

The reference implementation ships with primary keys only. Every lookup by a
foreign key (`chair_id`, `user_id`, `ride_id`, `livestream_id`, `tenant_id`)
or by a token scans the table. `rows_examined` is orders of magnitude above
`rows_sent`; MySQL CPU is the first bottleneck of the contest.

## Hypothesis template

Tables T1..Tn have only PRIMARY; handlers filter them by columns C and sort
by `created_at`/`updated_at`. Composite indexes on (C, sort column) turn
full scans into range reads, so the benchmark answers more requests.

## Change template

Add `INDEX` lines to the schema file that `/initialize` reloads (ISUCON14:
`sql/1-schema.sql`, tables recreated on initialize), or an `ALTER TABLE` run
from initialize when the schema is not reloaded. Index the columns in the
`WHERE` first, then the `ORDER BY` column. One experiment may hold several
indexes: it is one mechanism.

## Checklist

- `/initialize` has a time limit (30s in ISUCON12 and ISUCON14); index builds
  on the initial data count against it. Check the initialize duration in the
  benchmark log.
- Indexes the queries never use cost writes for nothing; ISUCON14 解説 notes
  its own example includes some unused ones.
- Confirm with `EXPLAIN` or the next observe dump that `rows_examined`
  dropped; otherwise the column order is wrong.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon14 | exp-001-secondary-indexes | 681/902 | 2945/3286 | +293% | 2+2 | 6 | promote | promote | 6 indexes in sql/1-schema.sql; recorded by kaizen-isucon14/bin (pre-plugin) |

## Notes from write-ups

- ISUCON13: initial ~3,000 → ~10,000 with the listed indexes (`livestream_tags`,
  `icons.user_id`, `reactions(livestream_id, created_at)`, ...).
- ISUCON12 予選: `visit_history` (3.2M rows, index on `tenant_id` only) needed
  `(tenant_id, competition_id, player_id, created_at)`; shrinking the table
  to one row per (tenant, competition, player) was the bigger win.
- ISUCON14 LayerX: first change of the day, 599 → 3282.
