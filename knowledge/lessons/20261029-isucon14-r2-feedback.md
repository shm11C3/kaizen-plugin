# ISUCON14 R2: measured feedback and operating lessons

- Mode: practice. Problem-specific evidence; this is not a new automation or skill.
- Environment: three c5.large apps and a separate c5.2xlarge benchmark VM, same AZ,
  Ubuntu24.04/Go1.23.2/MySQL8.0.46. Official AMI unavailable. Do not infer a historical
  rank from the raw score under these different benchmark conditions.
- Evidence: private practice fork `iikanjini-kaizen-agent/isucon-competition-practice-20261029-r2`,
  stable `6459cc2e0d97c51dd4786b6e2b8a0fe040740d29`; control state under
  `/srv/isucon/isu14-team-r2-20261029/state`; audit SSM `68f833af-5001-4705-9089-b90dc06f4b98`.

## Keep and extend

Early polling/log/connection changes, measured SQL changes, DB/app separation,
matching and notification work raised the initial1096/pass to the adopted
64988/68470/pass pair. Independent Luna work prepared a durable stats candidate
with initial-data and transaction checks in a few minutes; the resident integrator
performed deployment, comparison and rejection without a manual release gate.
Keep bounded implementation/related checks/commit handoffs and automatic integration.

## What the full evidence changes

- Nine samples with the same500ms source tree and recorded resource fingerprints
  ranged61956–68470, median65191. Bundle IDs differed. The accepted pair median66729
  was higher than the pooled median: preserve all samples, not just the good pair.
- Under the existing min(candidate)>max(baseline) comparison, extra candidate-only
  samples cannot remove an overlap already present in the fixed pool. Stop that
  automatic loop inconclusive; a new comparison needs an explicit changed cause or
  predeclared measurement plan. Do not redraw pairs until one promotes.
- Covering index, adaptive retry, matcher50ms, persistent stats and O_DIRECT did
  not clear the configured comparison. Less SQL work alone is not proof of score gain.
- Existing contestant logs showed about79% dissatisfaction for the combined
  pickup/drive movement criteria, around18–20% for matching and36% for dispatch.
  Collect these baseline metrics early. SSE/difference notifications are a next
  hypothesis, not an adopted improvement. The official specification and both
  published clients support SSE; frontend changes are unnecessary for that transport.
- Removing the chair-stats status predicate differed for two official initial
  chairs. Preserve seed exceptions when denormalizing. A durable stats table was
  locally equivalent but still did not improve this measured score.

## Reusable repairs and remaining procedure

- Overlay rollback restored original files or removed introduced ones (`d73b729`).
  Check the effective setting changed by an experiment, not only its source marker.
- Read-only ledger observers no longer take a writer reservation (`14cae4e`), and
  watch carries the actual error instead of guessing AWS authentication failure.
- Final verification used two reboots with a passing65510/errors0 sample between
  them, then compared48 newly registered chairs through the real API before another
  initialize. Data matched; the frontend rendered after reboot. Final SSM
  `d412fe5f-b24a-4ce7-a296-f8a33a7f92fd`.
- The first final wrapper exited0 after only a partial reboot: SSH consumed the
  remaining stdin-fed script. Run SSH-containing programs from a saved file with
  controlled stdin. Require the expected result/evidence, not exit0 alone.
- Stage events were absent and several tasks were claimed after implementation;
  claim-to-ready is not coding time. Claim before implementation for coordination,
  and report missing timing as unknown without adding mandatory instrumentation gates.

The next practice uses the human-selected official8-hour window including setup,
investigation, repair, coordination and final checks. This case-specific schedule
does not redefine every contest's duration. Retain the previous evidence and old
release for rollback; load the new release at an idle boundary.
