---
id: in-memory-state-no-db
name: Replace the database with process memory for hot state
stage: late
cost: 60+ min
risk: high
signature: none (chosen when MySQL CPU is the bottleneck after every query fix)
sources:
  - https://zenn.dev/ponyo877/articles/1e29255b9d19bf (ISUCON14 感想戦: MySQL 剥がし、再起動試験未対応、envcheck で失格)
---
## Symptom

Every query is already cheap and MySQL is still the CPU bottleneck; the
remaining cost is the round trips and transactions themselves.

## Hypothesis template

Holding the hot state (free chairs, waiting rides, coupons, totals) in
process memory removes the database from the hot path entirely; the
bottleneck moves to nginx/CPU.

## Change template

Typed maps with a mutex per concern; persistence only for what the restart
test checks; periodic or on-shutdown dump (`ExecStop`) and reload
(`ExecStart`) if persistence is required.

## Checklist

- The restart test: data must survive a reboot. ponyo877 never implemented
  the dump/reload and the result stayed unofficial.
- The environment check: leftover tooling (a profiler server in the same
  VPC) disqualified the live run. Clean up before the final check.
- Single-host state blocks multi-host app scaling unless the state owner is
  one process (gRPC matcher on its own host in the write-up).
- Not a contest-day default; a late bet with a hard revert plan.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- Order in the write-up: official fixes → MySQL removal (bottleneck moved to
  nginx) → nginx L7 distribution → runtime tuning (PGO, GOGC, JSON parsing).
