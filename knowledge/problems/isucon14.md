# isucon14 (ISURIDE)

Official 解説: https://isucon.net/archives/58869617.html. Planted bottlenecks
in the order the 解説 presents them, with the pattern id used here:

| order | what | pattern | numbers from sources |
|---|---|---|---|
| 1 | indexes on chairs, users, rides, ride_statuses, coupons, chair_locations | missing-secondary-index | Go ≈4000 after indexes; LayerX 599→3282; practice exp-001 681/902→2945/3286 |
| 2 | `GET /api/app/nearby-chairs` 2N+1 → 1 query | n-plus-one-query | — |
| 3 | `GET /api/owner/chairs` total distance | heavy-aggregate-query | LayerX filter-first 3282→3742; derived table later |
| 4 | matching: batch, nearest, distance cutoff, no randomness | random-order-matching | LayerX interval 3742→4169, multi-ride 4169→4981 |
| 5 | notification polling 30ms → `retry_after_ms`, cache | hot-polling-endpoint | LayerX 30→100ms 4981→5578; 解説: JSON cache ≥100k |
| 6 | `POST /api/chair/coordinate` async + bulk insert | single-row-insert-loop | — |
| 7 | payment Idempotency-Key | external-service-idempotency | 解説: close to a decoy |
| — | DB on its own host | db-busy-separate-host | LayerX 5578→10221 |
| — | access-token cache | auth-lookup-per-request | LayerX late |

Constraints: `/initialize` 30s, tables recreated on initialize (indexes go in
the schema), location visible within 3s but availability immediate,
`isuride-matcher` must run on one host only.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
| exp-001-secondary-indexes | missing-secondary-index | +293% | promote | median improved 29361 bp; worst candidate 2945 > best baseline 902 (kaizen-isucon14/bin, pre-plugin) |
