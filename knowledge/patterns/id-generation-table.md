---
id: id-generation-table
name: Ids dispensed by a MySQL generator table
stage: early
cost: 10-20 min
risk: low
signature: the index list names an id_generator/sequence table, or a REPLACE/UPDATE on such a table runs >=100 times
sources:
  - https://isucon.net/archives/56850281.html
---
## Symptom

Every new row (a CSV score row, a player, a competition) first does
`REPLACE INTO id_generator (stub) VALUES (?)` on MySQL and reads
`LAST_INSERT_ID()`. Each call is an autocommit write serialized on one row
lock; a bulk endpoint pays one MySQL round trip per row before it writes
anything, and concurrent uploads queue on the same row.

## Hypothesis template

Endpoint E spends most of its time dispensing ids one at a time from the
generator table; generating unique ids in process (or dispensing a block
per request) removes N MySQL round trips and the shared row lock.

## Change template

- In process: a 64-bit counter seeded from a timestamp at start (and reset
  in `/initialize`), formatted the way the old ids looked (hex here).
- Block dispense: one `UPDATE id_generator SET id = LAST_INSERT_ID(id + N)`
  per request, then hand out N ids locally.

## Checklist

- Ids must keep the shape the clients and the path regexes expect (hex
  without a prefix here); check `PATH_ID_REGEX` and the benchmarker's
  "does not exist" literal.
- Ids must stay unique across processes and across a restart during the
  run: seed from time, not from zero.
- `/initialize` resets the table's counter; the in-process generator must
  not fall below ids the initial data already holds.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon12-qualify | 005-inprocess-id-generation | 4430/4608/4608/4778 | 8226/8230/8493 | +79% | 4+3 | 4 | promote | promote | - |
