---
id: single-row-insert-loop
name: Many single-row INSERTs that could be one batch
stage: mid
cost: 15-30 min
risk: mid
signature: an INSERT digest without a VALUES list is executed >=1000 times, or a POST endpoint averages >=1 s over >=20 calls in the per-endpoint table
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
| isucon12-qualify | 003-upload-batch-dedupe | 2269/2389/2404/2708 | 2504/2641/2678 | +10% | 4+3 | 4 | inconclusive | promote | rule: inconclusive (median +1020 bp: 2504/2641/2678 vs 2269/2389/2404/2708; the 2708 baseline sample is the outlier the worst candidate must clear). Override to promote: plan item 3 (drop the reader flock) is only correct once the upload writes DELETE+INSERT atomically, which this change does; all candidates beat the baseline median by >= 450 bp. Mechanism note from the candidate's app log: upload 3677 -> 3050 ms avg, ranking 2049 -> 1462 ms, player 1327 -> 1672 ms: the per-row fsync was not the cost; the upload's time is waiting for the tenant flock and dispensing ids on MySQL per row while holding it. Prediction 'well under a second' was wrong. |
