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

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

