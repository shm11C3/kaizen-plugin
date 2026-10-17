# ISUCON Team Operating Policy

These instructions apply equally to Codex and Claude Code. Read
`team/docs/OPERATIONS.md` and `team/docs/RUNBOOK.md` before operating the target.
Paths are relative to the installed plugin root `K`. The competition clone
contains source and minimal bootstrap files, not these rules or management tools.

## Mission and autonomy

- Maximize the final valid score within the competition time budget. Improvement
  cycles and agent utilization are diagnostic metrics, not the objective.
- Work autonomously: inspect shared observations, discover and register tasks,
  atomically claim work, implement, validate locally, submit candidates, then
  continue with the next useful task. Do not wait for a new human prompt after
  every task.
- Use a unique session identifier such as `a-codex-01` or `b-claude-01`.
- Roles are dynamic. Any session may investigate or implement any area. Only
  the current integration owner may mutate the shared competition environment.
- Prioritize measured bottlenecks and the scoring path. Do not perform unrelated
  cleanup, speculative refactoring, or unmeasured modernization.
- Follow human strategy, time limits, exclusions, and stop requests.
- Follow `team/docs/REGULATIONS.md` for per-operation automated/manual methods
  and isolated sandbox validation. Official target integration stays serial.
- Use `skills/improve-workflow/SKILL.md` for recurring work: practice refines
  reusable skills but captures problem-specific procedures as knowledge;
  competition may also ship target-specific tools through private plugin main.
  Roll out pinned releases at an idle boundary; keep competition main separate.

## Shared state and task ownership

- The authoritative task database and environment reservation live on the
  control host at `/srv/isucon/state/team.sqlite3`. Never use separate local
  databases to coordinate different PCs. SQLite is local to that host, not on NFS.
- From a personal PC use `scripts/team/control.py`; on the control host use
  `scripts/team/team.py --db /srv/isucon/state/team.sqlite3`.
- A Discord claim announcement is a notification, not ownership. Proceed only
  after an atomic claim succeeds. Check for related tasks before creating one;
  ownership of different task IDs does not imply their changes are independent.
- Record hypothesis, evidence, base SHA, changed resources, dependencies, local
  validation, source SHA, risk, and rollback in the candidate template.
- After another change is accepted, recheck assumptions for affected tasks.
  Stop or revise work whose bottleneck or dependency disappeared.
- When candidates accumulate, prioritize integration support, validation, and
  analysis of collected artifacts over producing more unmeasured changes.
- If blocked, preserve the task and evidence, notify humans when needed, and
  continue independent useful work. Do not repeat a rejected hypothesis without
  new evidence or a materially revised mechanism.

## Experiment choice and strategy review

- Follow `team/docs/STRATEGY.md`: current scoring impact, evidence, uncertainty,
  all-in verification time, dependencies and disproof determine priority.
- A corpus hit or cheap implementation does not establish scoring value. Keep
  observation-derived options and structural alternatives in the plan.
- Review unexpected outcomes, repeated mechanisms and parameter oscillations at
  a stable boundary. AI investigates first; preserve human strategy and escalate
  only concrete choices under the adoption policy below.
- Use task kinds investigation/comparison/implementation and shared hypothesis
  keys. Local evidence work can finish without occupying the target. On READY
  backlog, automatic claims prefer evidence work; explicit task IDs remain an
  intentional choice, not permission to bypass integration or measurement.
- A structural candidate may contain inseparable prerequisite edits for one
  causal hypothesis. Test a combined candidate explicitly; do not count an
  unmeasured prerequisite as a verified improvement.

## Git and isolated implementation

- Each person uses their own clone. Separate concurrent sessions in one clone
  with worktrees. Preserve unrelated work.
- Branch from the current `origin/main`, e.g.
  `agent/a-codex-01/T-0001-query-index`. Workers never update `main` directly.
- Stage explicit files. Commit one coherent hypothesis, run appropriate local
  checks, push the branch, and submit its immutable full SHA.
- Only the integration owner may update `main`, using the measured integrated
  candidate. Use fast-forward updates; never force-push `main`.
- Do not create PRs or wait for PR approval during the competition.
- Keep secrets, cookies, private keys, database dumps, and large artifacts out
  of Git and Discord. `.local/`, `.kaizen/`, and runtime databases are untracked.

## Integration and measurement boundary

- Before integration, reserve the shared environment with `env-acquire`.
  Retain the reservation through deployment, any portal benchmark, result
  recording, adoption or recovery, and final state verification.
- Route target operations through `scripts/team/target.py`, which holds a local
  process lock and checks the reservation. Follow kaizen's scripts for deployment,
  verification, benchmarking, evaluation, recording, and recovery.
- Never bypass the boundary with direct SSH writes, rsync, service restarts,
  SQL mutations, profiling changes, log truncation, or portal benchmark runs.
  Observation setup/reset also belongs to the integration owner.
- The wrapper is an operational guard, not a hostile-user security boundary.
  Shared SSM access trusts team members. Instructions do not replace the
  deterministic checks in the underlying plugin.
- Never enable target operations until today's rules, source, target hosts,
  preset, baseline, and recovery drill are confirmed. The competition source
  layout is chosen when the day's initial code is imported.
- Install the same plugin release across members and the control host. Its hooks
  currently target Claude Code; Codex must follow the same procedures explicitly.
  Do not claim equivalent hook enforcement exists for Codex.
- Compare the current stable revision against the actual integrated candidate,
  not merely against the worker's source commit or original base.
- Keep source SHA, integrated candidate SHA, stable-before/after, host/config/DB
  changes, observation mode, samples, correctness, and decision together.
- A SHA alone cannot restore schema, indexes, data, or external configuration.
  Validate restoration of every changed resource before calling it recoverable.

## Adoption and human judgment

- Automatically adopt ordinary, bounded, reversible improvements only when
  correctness passes, measurement conditions are comparable, performance passes
  the configured evaluator, and no human-decision condition applies.
- Request human judgment for ambiguous adoption, broad changes with material
  risk, significant tradeoffs, or competing designs that affect architecture or
  strategy. Routine implementation details remain autonomous.
- Classify by semantics and recovery impact, not only line count or passing tests.
  Complete safe local implementation, tests, and comparison before asking.
- Obtain judgment before any shared-environment action whose material risk is
  itself the reason for escalation. A post-benchmark approval is too late for
  an irreversible operation.
- Present evidence, alternatives, recommendation, risks, and recovery. Cite the
  human decision in the durable experiment record; do not fabricate approval.
- Correctness failures are rejected and recovered; human judgment does not waive
  correctness or competition rules. Inconclusive measurements are not adoption.
- While a candidate awaits human judgment, restore stable and free the
  environment for other experiments. Reintegrate and remeasure if stable moves
  before that candidate is accepted.
- Missing data, noisy measurements and unexplained errors are NEEDS_MEASUREMENT,
  owned by AI investigation. NEEDS_HUMAN requires a concrete choice with options
  and a recommendation. Exhausting the measurement budget does not create a
  human decision by itself; preserve evidence and work on another useful task.
- Install/join success includes actual model readiness and matching control-host
  release. A filesystem-only check is not a joined member. Keep environment DB,
  target configuration and knowledge paths together and isolated for rehearsals.
- Stable includes the resource bundle, not only Git SHA. Probe/restore failures
  cannot be waived. Count every physical attempt, including recovery and portal
  reservations, within the configured project/hour/experiment budgets.

## Interruption, handoff, and finish

- Reservations do not expire automatically. A disconnected client does not prove
  that remote deployment or benchmarking stopped. Never steal or force-clear a
  reservation. Verify processes, all host revisions, and result artifacts first.
- Handoff at a stable boundary; transfer the reservation explicitly with
  `env-handoff` after verifying no target process is running. Update the task's
  owner separately where necessary.
- On human stop: start no new target action, let the active bounded operation
  finish safely, recover stable unless the candidate was accepted, record and
  report the final state. Continue no competition work after the stop.
- At freeze time, follow the runbook: deployment state, correctness, restart
  persistence, observation/debug settings, and final benchmark.
- Discord notifications should communicate claims, useful discoveries, submitted
  candidates, decisions, and failures. Do not invent delivery. If no connector
  is configured, provide a ready-to-post message to the human and keep canonical
  state on the control host.
