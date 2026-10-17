---
id: n-plus-one-query
name: Query per row inside a response builder or loop
stage: early
cost: 15-30 min
risk: mid
signature: a cheap SELECT by `column = ?` is called >=500 times returning <=2 rows per call
sources:
  - https://isucon.net/archives/58001272.html
  - https://isucon.net/archives/58869617.html
  - https://isucon.net/archives/56850281.html
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
- N+1 costs a network round trip per row once the DB is on another host;
  fix it before separating hosts.

- 007-nearby-chairs-single-query (isucon14): the single-query rewrite was
  rejected at n=2 (6524/9960 vs 7763/9538) while the run-to-run spread at
  that stage was ±20%; the endpoint is not on the scoring path once
  matching is fixed. With spread above the expected effect, two samples
  decide nothing: measure the baseline spread first and size n to it, or
  skip the experiment.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon14 | 007-nearby-chairs-single-query | 7763/9538 | 6524/9960 | -5% | 2+2 | 2 | reject | reject | map[25:13,26:1]; map[25:18] |
