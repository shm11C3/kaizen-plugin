---
name: prepare-candidate
description: "Prepare a claimed ISUCON team candidate from an evidence-backed hypothesis through implementation, related validation, commit and READY artifacts. Use for local worker preparation while the integration owner measures another candidate; does not grant target reservations or adoption authority."
---

# Prepare candidate

Set `K` to this skill's base directory `/../..` and `KAIZEN_PROJECT` to the
competition clone. Apply `../team/SKILL.md` for shared ownership and read
`../../team/docs/PIPELINE.md` for delegation, backpressure and time accounting.
Choose necessary pre-benchmark checks under `../../team/docs/VALIDATION.md`;
full regression, new coverage and independent/LLM review are not default gates.

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
3. Commit and freeze the source at an immutable full SHA before source-bound
   checks. Use a necessary build/load smoke and existing focused regression for
   the changed contract or observed failure; select cheap related lint under
   `../../team/docs/LINT.md`. Add real DB/concurrency checks or a focused
   reproducer when a concrete risk needs them, not as a universal gate. Preserve
   failures, diagnostic dispositions and explicitly skipped scope. Advisory
   formatting/style findings alone do not block READY. Keep assertions grounded
   in the specification.
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
   The main session remains the task owner and Discord contact. Within that same
   human-started session, it may explicitly delegate an exact task ID and its
   permitted `task-stage` / `task-ready` commands to a native subagent. When the
   existing authentication context and connection are available, the subagent
   executes those preparation commands as the parent SESSION principal, records
   its internal worker ID in reason/evidence and submits without waiting for the
   parent to relay READY. This is work under the same owner's responsibility,
   not a new member, separate join or authentication bypass. It grants no
   environment reservation, deploy, benchmark or adoption authority. Do not
   borrow another session/person's identity or newly share credentials or
   reservation tokens. If that connection is unavailable, return one concise
   machine-readable completion package (task, source/base SHA, paths, check
   results/evidence, durations, risks and recommendation); the parent submits
   it in one pass without a new approval wait or repeated investigation.

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
