---
id: nginx-l7-distribution
name: nginx CPU-bound on one host after the DB stopped being the bottleneck
stage: late
cost: 30-60 min
risk: mid
signature: none from the dump (host CPU: nginx near 100% on the bench-facing host while app hosts idle)
sources:
  - https://zenn.dev/ponyo877/articles/1e29255b9d19bf
---
## Symptom

Late in the contest, with the DB gone or idle, the host that receives the
benchmark spends its CPU in nginx (TLS, proxying) and the other hosts idle.

## Hypothesis template

Splitting nginx into an L4 layer on the bench-facing host and L7 layers on
every host (with upstream weights per capacity) spreads TLS and proxy CPU
across the three servers.

## Change template

`stream {}` block on host 1 forwarding to `http {}` nginx on hosts 1-3;
app on every host; weights tuned until CPU is level.

## Checklist

- Session-less app only; per-host caches diverge (see
  response-cache-with-invalidation).
- The portal's environment check may forbid or inspect extra listeners;
  read the manual.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

