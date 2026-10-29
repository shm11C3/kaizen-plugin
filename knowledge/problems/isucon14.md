# isucon14 (ISURIDE)

References (read, not reproduced): https://isucon.net/archives/58869617.html

Patterns worth checking on this problem, from reading the references and
the code: missing-secondary-index, n-plus-one-query, heavy-aggregate-query,
random-order-matching, hot-polling-endpoint, single-row-insert-loop,
external-service-idempotency, db-busy-separate-host, auth-lookup-per-request.

Constraints from the manual and code: `/initialize` 30s, tables recreated
on initialize (indexes go in the schema), location visible within 3s but
availability immediate, `isuride-matcher` must run on one host only.
A new chair counts as free from the moment its activation returns: every
position buffer or nearby-chairs cache delays it and raises code 31, and more
sales add more chairs, so faster turnover hits the 200 soft-error limit
(practice R3, see lessons/20261029-bench-soft-error-probe.md).

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
| exp-001-secondary-indexes | missing-secondary-index | +293% | promote | median improved 29361 bp; worst candidate 2945 > best baseline 902 (kaizen-isucon14/bin, pre-plugin) |
| 001-fsync-commit | fsync-on-commit | +6% | inconclusive | rule inconclusive: +5.9% median under ±15% noise; fsync setting alone does not move the score while matching bounds it |
| 002-notification-interval | hot-polling-endpoint | +53% | promote | rule decision as evaluated |
| 003-matching-interval | random-order-matching | -5% | reject | rule decision as evaluated |
| 004-nearest-chair-matching | random-order-matching | - | reject | correctness failure CODE=15: a chair was assigned a new ride before it was notified of the previous ride's completion; 'free' must mean all six statuses were sent to the chair, not evaluation IS NULL |
| 005-nearest-chair-matching-notified | random-order-matching | +123% | promote | rule decision as evaluated |
| 006-owner-chairs-filter-first | heavy-aggregate-query | +2% | inconclusive | rule decision as evaluated |
| 007-nearby-chairs-single-query | n-plus-one-query | -5% | reject | rule decision as evaluated |

The separate 2026-10-17 pilot is recorded in
[quality recovery and recurrence](../lessons/20261017-isucon14-quality-recovery.md).
Its single-host conditions and experiment IDs are separate from the runs above.

The 2026-10-18 tools/tests/preparation follow-up is recorded in
[tests and quality holds](../lessons/20261018-isucon14-tools-tests-phases.md).
Its20-minute run adopted0/3 experiments; candidate peaks are not final scores.
