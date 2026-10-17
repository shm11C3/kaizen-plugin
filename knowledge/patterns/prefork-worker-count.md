---
id: prefork-worker-count
name: Too few processes for a prefork runtime
stage: early
cost: 5 min
risk: low
signature: none from the digest (initial score far below the Go/Node/Rust implementations of the same problem; language is Ruby/Perl/Python/PHP)
sources:
  - https://isucon.net/archives/56850281.html
---
## Symptom

The benchmarker's concurrency exceeds the worker count; prefork languages
start well below the threaded/async implementations of the same app.

## Hypothesis template

Raising workers (memory permitting) lets the runtime accept the
benchmark's concurrency; find the count by measurement.

## Change template

Service unit or app server config (puma workers/threads, unicorn, gunicorn,
php-fpm pm.max_children) via the overlay; restart the service.

## Checklist

- Memory per worker × count must fit the host; check `free -m` after a run.
- DB connection count rises with workers; check `max_connections`.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

