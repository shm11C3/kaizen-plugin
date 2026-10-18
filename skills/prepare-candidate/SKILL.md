---
name: prepare-candidate
description: "Prepare a claimed ISUCON team candidate from an evidence-backed hypothesis through implementation, related validation, commit and READY artifacts. Use for local worker preparation while the integration owner measures another candidate; does not grant target reservations or adoption authority."
---

# Prepare candidate

Set `K` to this skill's base directory `/../..` and `KAIZEN_PROJECT` to the
competition clone. Apply `../team/SKILL.md` for shared ownership and read
`../../team/docs/PIPELINE.md` for delegation, backpressure and time accounting.

Take a claimed task with a current base, scoring hypothesis, allowed files and
resources, observable completion criteria, time budget and stop/repair conditions.
If these are missing, resolve them from the plan and evidence before editing;
do not invent deployment permission. The main session chooses priorities and
coordinates with other members through Discord.

1. Check the current stable, dependencies, prior attempts and relevant quality
   holds. Work as the sole writer in an isolated branch/worktree named with the
   member's GitHub login. A native subagent may own the complete preparation;
   otherwise the main session does it. Do not split every phase into a new
   instruction wait.
2. Implement the bounded mechanism. In parallel, independent work may inspect
   the specification, prior failures or test cases; it must not edit the writer's
   worktree. Use `../prepare-tests/SKILL.md` or `../refactor/SKILL.md` only for a
   concrete blocker with its own time limit and dependent improvement.
3. Commit and freeze the source at an immutable full SHA before running
   source-bound native lint and regression checks under
   `../../team/docs/LINT.md`. Use actual database/runtime checks when the change
   depends on them. Preserve failures and diagnostic dispositions. Add a focused
   reproducer for an observed defect; keep specification-backed assertions.
   If a repair is needed, finish pending checks, make a new commit and rerun
   the affected scope against its full SHA. Never move HEAD during a running
   check/build or bind a pre-commit result to a later untested commit.
4. Verify that check records name the actual tested SHA, scope, versions,
   conditions and durations, and match the source being submitted. If subsequent
   composition changes relevant source, the integrator checks that actual
   integrated SHA; a worker's result is not proof for an untested composition.
5. Complete `../../team/templates/CANDIDATE.md` with source/base, evidence,
   changed resources, related checks, remaining costs, recovery and open risks.
   Publish immutable source/artifact references accessible to other members.
   The authenticated task owner submits `task-ready` through the shared control
   interface and posts READY to its Discord thread. A subagent without that
   identity returns the complete submission package to the owner, who forwards
   it without a new approval or repeated investigation. Never share reservation
   tokens or impersonate another session.

Finish by the agreed time with READY, a bounded repair with preserved failure,
or a reasoned stop and the smallest next discriminating action. Unresolved
related local correctness checks cannot be called complete merely because
the code compiles; official score validation still follows READY. Report a new
quality failure through the existing hold procedure; preserve the original
candidate and evidence before repair. Missing evidence is AI work, not a human
approval request.

After the handoff, use current queue/Discord state to investigate the next
independent option or unblock a held candidate. Integration, deployment,
benchmarks and adoption remain with `../experiment/SKILL.md` and the target's
reservation holder. Local preparation never substitutes for an official score.
