---
id: missing-secondary-index
name: Missing secondary index on hot lookups
stage: early
cost: 5-15 min
risk: low
signature: a SELECT digest examines >=50x the rows it returns over >=20 calls, or a filtered table has only PRIMARY
sources:
  - https://isucon.net/archives/58869617.html
  - https://isucon.net/archives/58001272.html
  - https://isucon.net/archives/56850281.html
  - https://zenn.dev/layerx/articles/3bd55b77e047c4
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

- `/initialize` has a time limit in the manual (30s in ISUCON14); index builds
  on the initial data count against it. Check the initialize duration in the
  benchmark log.
- Indexes the queries never use cost writes for nothing; keep only the ones
  the digest shows being hit.
- Confirm with `EXPLAIN` or the next observe dump that `rows_examined`
  dropped; otherwise the column order is wrong.
- When `/initialize` only TRUNCATEs (ISUCON13: `sql/init.sql`, the CREATE
  TABLEs live in `initdb.d/` and never run again), put the `ALTER TABLE ...
  ADD INDEX` behind an information_schema existence check in the script
  initialize runs, so the second initialize does not fail on a duplicate
  index name (isucon13/001: 13 indexes, initialize stayed ~15s).
- The app's own queries may be invisible in the performance_schema digest
  table (server-side prepared statements); use the slow-log digest source
  before concluding there is no scan (isucon13 baseline dump looked clean).

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon14 | exp-001-secondary-indexes | 681/902 | 2945/3286 | +293% | 2+2 | 6 | promote | promote | 6 indexes in sql/1-schema.sql; recorded by kaizen-isucon14/bin (pre-plugin) |
| isucon13 | 001-add-secondary-indexes | 3601/3733/3867 | 6635/6815 | +80% | 3+2 | 3 | promote | promote | リクエストタイムアウト:GET:/api/tagx1,一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx3; リクエストタイムアウト:POST:/api/livestream/reservationx1,一般エラー:GET:/api/livestream/:id/reportx1,一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx1 |
