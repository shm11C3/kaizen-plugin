---
name: improve-workflow
description: "Improve recurring ISUCON operations. Refine reusable skills and supporting tools during practice and competition; preserve practice problem/environment-specific procedures as knowledge. During competition also build target-specific skills, test them, integrate into the private plugin main and roll out safely. Use for repeated commands, procedures or operator handoffs."
---

# Improve workflow

Read `../../team/docs/WORKFLOW.md`. Keep the competition source and plugin
source repositories distinct. Never edit an installed plugin cache.

1. Establish `practice` or `competition` from the human's instruction or session
   record. Classify the operation as reusable or problem/environment-specific.
   If mode or scope is unclear, collect evidence before distributing changes.
2. Collect actual occurrences, artifact references, time spent, failures and
   remaining repetitions. Check for an existing tool first.
3. For problem/environment-specific work in practice, write a lesson in shared knowledge,
   using `../../team/templates/WORKFLOW.md`. Include the proposed automation,
   validation and payoff. Stop at knowledge capture: no implementation, new
   skill, plugin-main merge or rollout for that specific procedure. Reusable
   skills and supporting tools may improve during practice; continue below and
   validate against another problem or fixture to avoid overfitting.
4. In competition, estimate remaining time saved minus implementation,
   validation, distribution and rollback time. If the payoff is too small or
   uncertain, capture the lesson and continue score work. In practice prioritize
   reproducible improvements transferable to other problems. Prefer a small script
   for deterministic commands and a skill for procedures requiring judgment.
5. Claim a tooling task and create a branch in the editable **plugin source**.
   Use `<github-login>/tooling/<task-or-topic>` for the member preparing it.
   Define inputs, outputs, target identity, failures and rollback. Reuse the
   deploy/bench/recovery mechanisms and preserve quality and authority rules.
6. Exercise the operation on representative local fixtures or an isolated test
   environment. Run the owning repository's required checks for scripts; validate
   skills and try a realistic task. Do not spend an official benchmark merely
   to validate documentation. Escalate only the existing human risk/tradeoff
   choices or a required manual action.
7. Give the commit, checks and lesson to the single plugin release owner. That
   owner verifies a clean plugin-main checkout and fresh origin/main, integrates
   the commit, reruns affected checks and pushes main normally. Fast-forward
   when possible; rebase/retest concurrent changes. No PR wait, force-push,
   competition-main update or direct worker-main write. Before publishing,
   verify the destination visibility: competition-specific skills and evidence
   belong in a team-private plugin fork/pack main, never a public upstream.
8. Pin the release SHA and roll out at an idle boundary. Record each PC/control
   host's **actually loaded** SHA. Finish active commands with their original
   version; do not replace the measurement core in an open experiment. If a
   reload needs a new session, keep rollout pending until it has started.
   Retain the old pinned release for rollback.
9. Measure subsequent saved time and link lesson, commit, checks and release.
   Retire an automation that costs more than it saves.

Keep independent source work moving during manual or release waits. A merge
does not prove that all agents loaded the release.
