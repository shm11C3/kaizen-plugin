---
name: recover
description: "Put every server back on the stable revision and prove it. Use when a candidate failed, the human says stop, a deploy was interrupted, or status shows deployed != stable with no open experiment."
---

# Recover

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup).

```bash
$K/scripts/status.sh
$K/scripts/recover.sh        # stable code + configured resource restore + bundle verification
$K/scripts/status.sh
```

recover.sh clears REVERT_PENDING only after files, target configuration and
declared resource fingerprints match the captured stable bundle. See
`$K/team/docs/RECOVERY.md`. If it fails, the target is in an unknown state: read the
error, fix the host by hand only as far as needed for deploy.sh to succeed
(a stuck service, a full disk), run recover.sh again, and tell the human
what was done. Do not start or continue an experiment until it succeeds.

If an experiment is open, close it afterwards with
`$K/scripts/evaluate.sh` and `$K/scripts/experiment.sh record <reason>`
so the record shows what happened; the Stop hook will ask for this.

A stale `.kaizen/bench.lock` (no deploy or benchmark running, confirmed with
`ps`) is removed with `rmdir .kaizen/bench.lock`.
