---
id: db-busy-separate-host
name: Database and application compete for one host
stage: mid
cost: 20-40 min
risk: mid
signature: DB statement time >= 60% of the benchmark duration (the DB saturates a core)
sources:
  - https://zenn.dev/layerx/articles/3bd55b77e047c4 (ISUCON14 LayerX: DB を別インスタンスへ 5578→10221)
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: 3 台構成の例)
  - https://isucon.net/archives/58869617.html (ISUCON14 解説: isuride-matcher と複数台構成の fail)
---
## Symptom

After the cheap DB fixes, MySQL still uses most of one host's CPU while
the application and nginx share the rest; two of the three servers idle.

## Hypothesis template

Moving MySQL to its own host gives the application the whole first host and
the database the whole second; throughput roughly follows the freed CPU.

## Change template

1. On host 2: MySQL listens on the private address (`bind-address`), user
   grants for the app host, data restored from host 1 (or initialize).
2. On host 1: `env.sh`/config points `DB_HOST` at host 2; MySQL stopped.
3. Later: host 3 as a second application server behind nginx upstream
   (`weight` per capacity; see nginx-l7-distribution).

All of it is overlay/config plus a deploy; record which host holds what in
the manifest.

## Checklist

- Background workers that must run once (ISUCON14 `isuride-matcher`) must
  run on exactly one host; the 解説 reports multi-host benchmark failures
  from duplicated matchers.
- N+1 queries become network round trips: fix them first or the move can
  lose score (ISUCON12 解説).
- The restart test restarts every host; services must come up in the right
  order (MySQL before the app) without manual steps.
- `/initialize` now initializes a remote DB; check its duration.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- LayerX (ISUCON14): DB separation nearly doubled the score early
  (5578→10221); they later regretted using only two of three hosts.
- ISUCON13 解説 layouts: with heavy DNS, [DNS + DNS DB] / [nginx + app] /
  [app DB]; after DNS fixes, [nginx + DNS + DNS DB] / [app] / [app DB].
