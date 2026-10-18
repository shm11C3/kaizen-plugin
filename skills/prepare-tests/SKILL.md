---
name: prepare-tests
description: "Select or add focused, specification-backed checks for a concrete ISUCON change or observed quality failure. Use when existing checks cannot answer that risk or a held candidate needs a reproducer; broad preparation is optional rather than a gate before every benchmark."
---

# Prepare tests

Read `../../team/docs/VALIDATION.md` and `../../team/docs/PHASES.md`. The official
real benchmark checks performance and checker correctness for adoption. Local
checks cheaply catch concrete defects before it; use native tools rather than
a replacement test framework. Scope lint under `../../team/docs/LINT.md` and
retain source-bound results, diagnostics and untested scope.

1. Read the actual specification, checker and current scoring paths. List the
   invariants affected by the current high-priority candidates: authorization/ownership, state transitions,
   amounts/aggregation, initialization, persistence, visibility and concurrency.
   Current output is a characterization, not automatically the correct contract.
   Prioritize a reproducer for observed warnings/correctness defects relevant to
   the planned change before unrelated coverage; preserve an explicit gap if
   reproduction is unavailable.
   Name which near-term candidate each check protects. Do not spend the whole
   budget on easy pure helpers while the planned SQL/concurrency change remains
   untested; record that gap. A human may deliberately choose broader preparation.
2. Claim a scoped test task. Other members continue source analysis and observation
   in independent clones; do not block all implementation until coverage is complete.
   Set a time budget and the improvements these checks will unblock in the plan.
3. Prefer existing focused regression for the changed contract or observed
   failure. Add a reproducer or API/DB/concurrency check when it answers a
   concrete risk more cheaply or directly, or covers a gap in the checker.
   Do not duplicate cheap existing checks. Use a real
   database when transaction semantics matter; mocks alone cannot prove that
   behavior. Isolate/reset test data. New broad coverage is not a submission gate.
4. Freeze an immutable commit before source-bound execution. Select the relevant
   package/crate and named tests, e.g. Go `go test -count=1 -run '^TestChangedContract$' .`
   or Rust `cargo test --locked -p PACKAGE changed_contract`. Optionally wrap the
   chosen command with `python3 "$K/scripts/check.py" --project MODULE_PATH --label focused --timeout 120 -- ...`.
   The wrapper retains command, source fingerprint, time and logs. A timeout,
   changed source during the run, missing dependencies or skipped test is not a pass.
5. Verify sensitive tests reject an actually broken case or the original held SHA.
   Keep failure evidence, then verify the repaired version passes. Do not weaken
   expectations to make an optimization green; resolve specification ambiguity first.
6. Submit shared test source through the normal Git/integration process. Record
   remaining gaps and stop at the budget. Expand coverage when a new risk/failure
   justifies it, not to reach a percentage.

Do not require broad regression, race or a separate review on every integration.
Use those only for a named risk with a time budget. Race-enabled builds and
profilers are diagnostic runs; do not use their throughput as score evidence.
Known local correctness failures still need repair/hold even if a benchmark
passes; new broad test preparation is not required merely to reach READY.
A later quality hold gains a linked reproducer and repair rather than discarding
its candidate or sending unfinished investigation to the human.

For DB/external-state tests, disable inappropriate result caching (Go: -count=1)
and inspect native skips/no-test output. A wrapper process pass alone does not
establish that integration assertions actually ran. Keep known baseline tool
diagnostics separate; repair them explicitly rather than silently disabling checks.

Keep the test's worktree stable until the command has actually exited. Run a
parallel patch/composition comparison in a different worktree; owning two tasks
does not make branch switching during an active test safe. A detected source/HEAD
change invalidates the check, even when the native command exits0.
