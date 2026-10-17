---
id: coarse-file-lock
name: One coarse lock (flock, mutex) around every read and write of a tenant or table
stage: mid
cost: 15-30 min
risk: mid
signature: none from the dump (code: flock/sync.Mutex taken on read paths; read endpoints slow although their queries are indexed)
sources:
  - https://isucon.net/archives/56850281.html
---
## Symptom

Read endpoints stay slow after their queries are indexed: the per-endpoint
table shows seconds of latency for a handler that does a few PK lookups.
The time is spent waiting for a lock that writers hold for their whole
row-by-row loop and that readers take too (isucon12: `flockByTenantID`
around ranking, player, billing and the CSV upload).

## Hypothesis template

Readers wait on lock L that only protects against a partial write; once
the write is one transaction, the database's isolation gives readers a
consistent view and L can be dropped from the read paths, so reads of one
tenant run in parallel.

## Change template

1. Make the writer atomic first (one transaction, see
   single-row-insert-loop); keep the lock on the writer.
2. Remove the lock from the read paths.
3. If the writer must stay long, shrink its critical section: validate
   and prepare rows before taking the lock.

## Checklist

- A reader that starts between a DELETE and the INSERTs sees an empty
  result unless the write is one transaction; do step 1 first.
- SQLite rollback journal: readers get SQLITE_BUSY during the commit;
  the driver's busy timeout must be set (go-sqlite3 defaults to 5 s).
- Measure the read endpoint's latency per request after the change; if
  it stays high, the cost is CPU, not the lock.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon12-qualify | 004-drop-reader-flock | 2504/2641/2678/2716 | 4430/4608/4778 | +73% | 4+3 | 5 | promote | promote | - |
