---
name: prepare-tests
description: "Build a fast, specification-backed regression foundation before aggressive ISUCON changes, and turn observed quality failures into reproductions. Use during initial preparation, before risky optimization/refactoring, or when a held candidate needs a repair."
---

# Prepare tests

Read `../../team/docs/PHASES.md`. Use existing language test tools and the
provided official checker; the plugin records execution, not a replacement test framework.

1. Read the actual specification, checker and current scoring paths. List the
   invariants affected by likely changes: authorization/ownership, state transitions,
   amounts/aggregation, initialization, persistence, visibility and concurrency.
   Current output is a characterization, not automatically the correct contract.
2. Claim a scoped test task. Other members continue source analysis and observation
   in independent clones; do not block all implementation until coverage is complete.
   Set a time budget and the improvements these checks will unblock in the plan.
3. Start with fast API/DB integration checks for those contracts and critical edge
   cases. Use the real database when its transaction semantics matter; mocks alone
   cannot prove visibility, ordering or SQL equivalence. Isolate/reset test data.
4. Use native tools (Go: go test ./...; Rust: cargo test); optionally run:
   `python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT" --label regression --timeout 120 -- go test ./...`.
   For Rust use cargo test through the same wrapper. Select the module/crate
   directory as --project when needed. The wrapper retains command, source fingerprint, time and logs. A timeout, changed
   source during the run, missing dependencies or skipped integration is not a pass.
5. Verify sensitive tests reject an actually broken case or the original held SHA.
   Keep failure evidence, then verify the repaired version passes. Do not weaken
   expectations to make an optimization green; resolve specification ambiguity first.
6. Submit shared test source through the normal Git/integration process. Record
   remaining gaps and stop at the budget. Expand coverage when a new risk/failure
   justifies it, not to reach a percentage.

Run fast relevant checks before source submission, broader regression before
integration, and the official benchmark for adoption. Race-enabled builds and
profilers are diagnostic runs; do not use their throughput as score evidence.
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
