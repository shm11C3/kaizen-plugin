# ISUCON14: tests, tools and preparation follow-up (2026-10-18)

Evidence: [private validation report](https://github.com/shm11C3/isucon14-policy-validation-20261018/blob/main/REPORT.md),
its EVIDENCE.json, frozen-inputs.json and local raw artifacts. This is a separate
20-minute operational follow-up, not a controlled comparison with the45-minute pilot.
Three independent Codex CLI actors used separate local clones and a transport
fixture while Discord was explicitly deferred. One app c5.large and one benchmark
c5.xlarge were used; this is not the official multi-server configuration.

| candidate | normal scores | reported warnings | result |
|---|---|---|---|
| initial | 1084 / 838 | none / CODE26:1 | starting official PASS baseline |
| ride status index | 1835 / 1994 | CODE25:7 / CODE25:3 | inconclusive, recovered |
| index + location index + owner filter | 2846 / 2390 | CODE26:1 / CODE26:1 | inconclusive, recovered |
| same application content, fresh integration SHA | 2646 / 2309 | none / CODE26:2 | inconclusive, recovered |

All six candidate samples were official PASS. Adoption was0/3; the maximum2846
was not the final stable score. Missing request denominators left warning quality
unknown. Initial stable a09a950 remained selected. Query repair removed the new
owner-timeout warnings in these samples, but did not resolve intermittent distance
freshness. Do not call it a fully repaired candidate or reroll until a clean pair.
Application Go/SQL trees in experiments002/003 were identical despite different
cherry-picked commit SHAs. Hold lineage must follow source/content and conditions.

Initial test preparation was about one minute according to the worker's phase
record and ran alongside SQL analysis. A broken fixed-fare implementation was
actually rejected; the restored code passed. Ordinary go test exposed a preexisting
slog vet diagnostic, which was repaired in a separate commit. Tests and diagnostic
repair remained shared candidates, included in integration experiments; no final
main adoption occurred. The suite protected fare/sales helpers, not the failing
notification/visibility path. Its contribution to final score was not established.
Twenty-four native check invocations took21.403 seconds in total; this is command
time, not authoring/coordination time, and includes cached/failed checks.

SQL observation used actual MySQL slow logs and pt-query-digest3.7.0 (11 classes).
Its observed991-point sample was excluded from adoption. alp1.0.22 checksum and
execution were verified, but existing nginx logs lacked duration, so timing analysis
was not claimed. A separate Go fixture emitted OTel1.31.0 HTTP spans and served
private pprof; Rust native-test success and a failing assertion were verified.
Neither OTel on the ISUCON app nor a Rust competition benchmark was performed.

Operational lessons:

- Same-session parallel tasks can still race on one clone's HEAD. A comparison
  and an index task mixed branch state; the collision commit was quarantined.
  Separate mutable workflows with worktrees and serialize mutation per worktree.
- Quality was held in prose/NEEDS_MEASUREMENT, while dedicated quality_holds had0
  rows. The release entrypoint now explicitly routes quality failures to
  task-quality-hold before resubmission and requires official repair evidence.
  This guidance refinement was not rerun in another full20-minute session.
- Prefer tests for the next measured candidate. Pure helper/SQLite checks cannot
  establish MySQL transaction visibility; prepare an isolated real-DB fixture
  with existing Go/Rust tooling when that is the actual repair blocker.
- No concrete structural blocker required a refactor in this run. The refactor
  skill's timebox/payoff procedure is implemented, but its score benefit is untested.
- An empty pre-created knowledge directory caused four initial target calls to
  fail. The coordinator initialized it autonomously. Future rehearsals should
  exercise one reserved target status call before the clock and let the configured
  bootstrap create the corpus; this was a fixture preparation error.

No human optimization advice was sent during the timed run. Expensive preparation,
initial samples and fixed-source final verification are outside its20-minute clock
and separately documented. Different duration, known problem, local transport,
partial usage reporting and lack of a control arm prevent a causal score claim.
Problem-specific repair mechanics remain knowledge; no ISUCON14-only skill was added.
