---
name: refactor
description: "Create a bounded ISUCON preparation phase when concrete code coupling repeatedly obstructs an optimization or quality repair. Preserve behavior with existing contract tests, separate the structural change from the optimization, and measure its downstream payoff."
---

# Refactor

Read `../../team/docs/PHASES.md`. Apply the team reservation boundary and
current Discord decisions. This skill is a deliberate strategy option, not
permission for repository-wide cleanup or a mandatory periodic rewrite.

1. Identify a concrete blocker: a query duplicated across hot paths, transaction
   logic that cannot be tested, or repeated conflicting edits. Name the next
   optimization/repair it prevents, with evidence and estimated repeated cost.
2. Compare direct repair against a small structural change. Timebox the phase,
   reserve regression/benchmark/recovery time, and state the stop condition and
   expected downstream savings. Prefer an existing library/tool if it solves it.
3. Use the prepare-tests skill for the relevant contracts before restructuring.
   Check a failing case as well as normal behavior. Record known baseline defects.
4. Work on `<github-login>/T-NNNN-summary`, using an implementation task and
   clear refactor hypothesis. Keep structural and behavioral/performance edits
   in separate commits so they can be inspected and measured independently.
5. Preserve API/SQL/ordering semantics and rollback boundaries. Run native
   regression checks, optionally using scripts/check.py for time/source evidence.
   Verify on the target before adoption; green local tests alone are insufficient.
6. If the refactor alone has no demonstrated score gain, do not label it a
   performance success. It may be measured as an explicit prerequisite combination
   with the named optimization; record both the combined gain and preparation cost.
   Size and architectural options alone do not require approval. Adopt a verified,
   recoverable gain within the agreed limits autonomously; escalate a concrete
   unresolved choice under `../../team/POLICY.md`. Missing evidence is AI work.
7. Stop if the payoff no longer fits the remaining time. Revert/defer cleanly,
   preserving tests and findings where useful. After the dependent change, record
   actual implementation/repair time and whether the anticipated seam helped.

Do not split a coherent transaction simply to reduce function length. Avoid
renames/formatting unrelated to the blocker. Shortening code is not the objective.
