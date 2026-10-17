---
id: prefork-worker-count
name: Too few processes for a prefork runtime
stage: early
cost: 5 min
risk: low
signature: none from the digest (initial score far below the Go/Node/Rust implementations of the same problem; language is Ruby/Perl/Python/PHP)
sources:
  - https://isucon.net/archives/56850281.html (ISUCON12 予選 解説: Go/Node/Rust 約2500、Ruby/Perl/Python/PHP 約1500、puma worker 32)
---
## Symptom

The benchmarker's concurrency exceeds the worker count; prefork languages
start at roughly 60% of the score of the threaded/async implementations.

## Hypothesis template

Raising workers to 30-50 (memory permitting) lets the runtime accept the
benchmark's concurrency; initial score approaches the async languages'.

## Change template

Service unit or app server config (puma workers/threads, unicorn, gunicorn,
php-fpm pm.max_children) via the overlay; restart the service.

## Checklist

- Memory per worker × count must fit the host; check `free -m` after a run.
- DB connection count rises with workers; check `max_connections`.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- Only applies when the team competes in a prefork language; the Go
  practice runs never trigger it.
