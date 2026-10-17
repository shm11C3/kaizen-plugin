---
id: single-row-insert-loop
name: Many single-row INSERTs that could be one batch
stage: mid
cost: 15-30 min
risk: mid
signature: an INSERT digest without a VALUES list is executed >=1000 times
sources:
  - https://isucon.net/archives/56850281.html
  - https://isucon.net/archives/58869617.html
---
## Symptom

A high-frequency write endpoint (location report, CSV upload row loop)
issues one INSERT per call or per row; each pays a round trip and, with
fsync on commit, a disk flush. The client waits for the write before its
next action (ISUCON14 chairs do not move until coordinate returns).

## Hypothesis template

Buffering writes in memory and flushing them as one multi-row INSERT every
few hundred milliseconds (or deduplicating rows before insert) removes most
round trips and flushes, and the client's next action starts sooner.

## Change template

- Bulk: collect rows, `INSERT INTO t (...) VALUES (...),(...)` on a timer or
  size threshold; respond before the flush when the manual allows a grace
  (ISUCON14: 3 seconds for location visibility).
- Dedupe: when only the last row per key matters, keep the last row per
  key and insert once.

## Checklist

- Reads that must see the write immediately (availability, latest status)
  need the in-memory value, not the table, until the flush lands.
- Flush on shutdown and before `/initialize` returns, or the restart test
  and the next run see missing rows.
- Error handling: a failed batch must not drop the whole buffer silently;
  record what happens in the manifest.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

