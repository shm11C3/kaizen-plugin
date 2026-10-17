---
id: response-cache-with-invalidation
name: Cache a response or derived state and invalidate on the writes that change it
stage: mid
cost: 30-60 min
risk: high
signature: none (chosen from the endpoint cost and the manual's freshness windows, not from a digest)
sources:
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: ranking は CSV アップロード時だけ変わる、失格は 3 秒猶予)
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: 位置情報は 3 秒猶予だが割当可否は即時)
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: アイコン更新は 2 秒以内に反映)
---
## Symptom

An expensive read whose result changes only on specific writes (ranking on
CSV upload, player on upload/disqualify, icon on update, ride status on
transition).

## Hypothesis template

The manual bounds staleness per field; caching the response and purging it
on the writes that change it keeps every field inside its window and turns
the read into a map lookup.

## Change template

Per-key map (or Redis if hosts must share) + explicit purge calls in each
write path; or a short TTL equal to the manual's grace. Write the
freshness window of every cached field in the manifest.

## Checklist

- List every write path that changes the cached value; a missed one is a
  correctness failure the benchmark will find late.
- Mixed windows: ISUCON14 location may lag 3s but availability must be
  immediate, so the whole nearby-chairs response cannot be cached for 3s.
- `/initialize` clears every cache (the most common cause of a failed
  second benchmark run).
- Multi-host: a process-local cache diverges between app hosts; purge must
  reach all of them or the cache must live in one place.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- ISUCON12: many teams qualified with SQLite plus ranking/player caches.
- Highest correctness-failure risk of the catalog; keep each cache its own
  experiment so a failure is attributable.
