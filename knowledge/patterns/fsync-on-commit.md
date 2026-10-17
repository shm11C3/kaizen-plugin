---
id: fsync-on-commit
name: COMMIT waits on fsync for every transaction
stage: early
cost: 5-10 min
risk: low
signature: COMMIT accounts for >=20% of DB statement time at >=2ms per commit
sources:
  - https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit
---
## Symptom

The digest's top entry is `COMMIT` with a single-digit-millisecond average
and thousands of calls; the write-heavy endpoints (location updates, status
inserts) are bounded by disk flushes, not by CPU.

## Hypothesis template

Every transaction flushes the redo log to disk; with
`innodb_flush_log_at_trx_commit=2` the log is written per commit and
flushed once a second, so commits return in microseconds and the
write-heavy endpoints stop queueing on the disk.

## Change template

Add a file under `etc/mysql/mysql.conf.d/` (deployed by the overlay, which
restarts `mysql.service`):

```
[mysqld]
innodb_flush_log_at_trx_commit = 2
sync_binlog = 0
```

Verify with `SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit'` after
the restart.

## Checklist

- The restart test (再起動試験) at the end of the contest restarts the
  machine cleanly; a clean restart loses nothing with value 2. Only an OS
  crash loses up to one second of commits.
- If binary logging is on, `sync_binlog=0` matters as much; check
  `SHOW VARIABLES LIKE 'log_bin'`.
- Confirm the mysql restart actually happened (overlay restarts only when a
  file under `etc/mysql/` changed).

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Observed

- ISUCON14 practice (2026-10-17 observation after one benchmark): COMMIT
  114s total, 12,897 calls, 8.85ms average on the initial implementation.
