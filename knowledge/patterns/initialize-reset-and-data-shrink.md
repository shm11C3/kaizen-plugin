---
id: initialize-reset-and-data-shrink
name: Initial data larger than needed and a slow or incomplete /initialize
stage: early
cost: 10-30 min
risk: mid
signature: none from the digest (read the initialize duration in the benchmark log and the row counts in the dump)
sources:
  - https://isucon.net/archives/56850281.html
  - https://isucon.net/archives/58869617.html
---
## Symptom

Tables carry history rows the application never needs (only `MIN` or the
last row per key is read); `/initialize` reloads them every run and must
finish within the manual's limit (30s in ISUCON14).

## Hypothesis template

Reducing the initial data to the rows that can be read (one per key) and
preparing it once (a trimmed dump restored by initialize) cuts initialize
time and every query that touched the history.

## Change template

- Trim at build time: generate a reduced dump from the initial data; make
  `/initialize` restore it instead of the original.
- Add indexes and derived tables into the same restore path so they exist
  after every run.
- If restore is slow: physical copy of the data directory or `LOAD DATA`
  instead of row-by-row INSERTs.

## Checklist

- Every field the benchmark reads must survive the trim; a row dropped
  because "only the last matters" fails when an endpoint lists history.
- Initialize duration measured before and after; it is a hard limit.
- Keep the original dump in the repo; the trimmed one is a build output.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

