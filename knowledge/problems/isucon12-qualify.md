# isucon12-qualify (ISUPORTS)

References (read, not reproduced): https://isucon.net/archives/56850281.html

Patterns worth checking on this problem, from reading the references:
initialize-reset-and-data-shrink (per-tenant SQLite, large initial data,
initialize time limit), missing-secondary-index, single-row-insert-loop,
response-cache-with-invalidation, heavy-aggregate-query (billing),
n-plus-one-query, prefork-worker-count. Not yet in the catalog: a coarse
file lock around reads, id generation through an auto_increment table,
backpressure with 429; write them as new patterns when measured.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
| 001-sqlite-player-score-index | missing-secondary-index | - | inconclusive | candidate-2 passed at 2386 (+15.6% over the 2064.5 baseline median) but the candidate sample failed with 3 errors because unattended-upgrades replaced mysql-server 8.0.34->8.0.46 and restarted mysqld mid-run (apt history 09:14:30); the upgrade also ran at half a core during the baseline samples, so neither side is a clean measurement. Retry the same index change after the host is quiet and the baseline is retaken. candidateRevision is the records-untrack commit on top of the benchmarked bdc8527 (same code). |
