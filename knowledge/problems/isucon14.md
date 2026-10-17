# isucon14 (ISURIDE)

References (read, not reproduced): https://isucon.net/archives/58869617.html

Patterns worth checking on this problem, from reading the references and
the code: missing-secondary-index, n-plus-one-query, heavy-aggregate-query,
random-order-matching, hot-polling-endpoint, single-row-insert-loop,
external-service-idempotency, db-busy-separate-host, auth-lookup-per-request.

Constraints from the manual and code: `/initialize` 30s, tables recreated
on initialize (indexes go in the schema), location visible within 3s but
availability immediate, `isuride-matcher` must run on one host only.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
| exp-001-secondary-indexes | missing-secondary-index | +293% | promote | median improved 29361 bp; worst candidate 2945 > best baseline 902 (kaizen-isucon14/bin, pre-plugin) |
| 001-fsync-commit | fsync-on-commit | +6% | inconclusive | rule inconclusive: +5.9% median under ±15% noise; fsync setting alone does not move the score while matching bounds it |
