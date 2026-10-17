# isucon12-qualify (ISUPORTS)

Official 解説: https://isucon.net/archives/56850281.html. Theme: several
valid approaches (SQLite single host, MySQL migration + multi-host, fast
restore, caching). Reference Ruby + SQLite single host reached ≈24,000
(qualifying level) with the changes below.

| order | what | pattern | numbers from sources |
|---|---|---|---|
| 1 | SQLite vs MySQL migration (CSV + LOAD DATA, physical restore, initialize 30s) | initialize-reset-and-data-shrink | player_score 3.7M rows |
| 2 | visit_history covering index (tenant_id, competition_id, player_id, created_at); keep MIN row only | missing-secondary-index / initialize-reset-and-data-shrink | 3.2M → 200k rows |
| 3 | flock around ranking reads → one transaction for DELETE+INSERT | (no pattern yet: coarse lock) | — |
| 4 | player_score duplicate rows → last row per player | single-row-insert-loop | 3.7M → 180k, "turning point" |
| 5 | ranking and player API caches, purge on upload/disqualify (3s grace) | response-cache-with-invalidation | many teams qualified with SQLite + cache |
| 6 | billing computed once at competition finish | heavy-aggregate-query | — |
| 7 | auto_increment ID table → UUID/ULID | (no pattern yet: id generation) | — |
| 8 | N+1 reads and row-by-row inserts | n-plus-one-query / single-row-insert-loop | — |
| 9 | prefork worker count 30-50 | prefork-worker-count | 1500 → ≈2500 initial |
| 10 | 429 + Retry-After on tenant add / competition start | (no pattern yet: backpressure) | — |

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
