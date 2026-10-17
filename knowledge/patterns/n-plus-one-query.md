---
id: n-plus-one-query
name: Query per row inside a response builder or loop
stage: early
cost: 15-30 min
risk: mid
signature: a cheap SELECT by `column = ?` is called >=500 times returning <=2 rows per call
sources:
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: fill*Response 系の N+1)
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: nearby-chairs の 2N+1 を 1 クエリに)
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: 参照の N+1 と行ごとの INSERT)
---
## Symptom

A list endpoint fetches N parent rows, then one or two queries per row
(`fillUserResponse`, `fillLivestreamResponse`, per-chair latest location).
The digest shows a tiny query with a huge call count; the endpoint's latency
grows linearly with page size.

## Hypothesis template

Endpoint E builds its response with one query per row of T; fetching the
rows of U for all ids at once (JOIN, `WHERE id IN (...)`, or a window
function for "latest per key") removes N round trips per request.

## Change template

Pick one endpoint. Replace the per-row query with a JOIN or a single `IN`
query keyed by the parent ids, build a map in memory, fill the response from
the map. For "latest row per key" use `ROW_NUMBER() OVER (PARTITION BY key
ORDER BY created_at DESC)` or a dedicated latest-state table (see
heavy-aggregate-query). Keep the JSON shape identical.

## Checklist

- Response field order and nullability must not change; the benchmarker
  diffs the shape.
- Rows missing from the batch query (deleted user, no location yet) must
  produce the same null/empty value the loop produced.
- ISUCON12 解説: teams that moved to MySQL without fixing N+1 died on network
  latency; N+1 matters more once the DB is on another host.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- ISUCON14 `GET /api/app/nearby-chairs`: 2N+1 queries → 1, with
  `rides.evaluation IS NULL` to decide availability.
- ISUCON13: five `fill*Response` functions; the 解説 lists JOIN, preload, or
  cache as the three remedies.
