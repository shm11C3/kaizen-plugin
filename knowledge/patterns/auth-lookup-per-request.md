---
id: auth-lookup-per-request
name: Session or token looked up in the DB on every request
stage: mid
cost: 10-20 min
risk: low
signature: a SELECT on access_token/session is called for >=15% of requests
sources:
  - https://zenn.dev/layerx/articles/3bd55b77e047c4 (ISUCON14 LayerX: アクセストークンのオンメモリキャッシュ)
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: 参加者 API のキャッシュ)
---
## Symptom

Middleware resolves the caller (`SELECT * FROM users WHERE access_token = ?`,
same for chairs and owners) on every request. Cheap per call, but it is one
query per request on the busiest path and the row never changes.

## Hypothesis template

Tokens map to immutable identities; a process-local map filled on first
lookup (or at initialize from the table) removes one query from every
request without changing any response.

## Change template

A `sync.Map`/mutex-guarded map keyed by token holding the user/chair/owner
struct; fill on miss; insert on registration; clear in `/initialize`.

## Checklist

- Registration endpoints must insert into the map (or the first request
  after registration misses and loads it; both are fine).
- Fields that do change (`chairs.is_active`) must not be served from this
  cache unless the write path updates it; cache the identity, not the state.
- `/initialize` clears the map.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- ISUCON14 practice observation: 2,100 token lookups for ~11,900 requests on
  the initial implementation (chair/app notification polls dominate).
