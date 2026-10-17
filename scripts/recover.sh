#!/usr/bin/env bash
# recover.sh
# Redeploy the stable revision and prove the host matches it. Run after
# reject or inconclusive, after a failed candidate, and whenever the human
# says stop while a candidate is deployed. Also the drill that setup runs
# before the first experiment: the loop must not start without this working.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

stable=$(state_get STABLE_REV)
[ -n "$stable" ] || die "STABLE_REV is not set; nothing to recover to"
start=$(epoch)
status=failed
trap 'record_step recover "$(short "$stable")" $(( $(epoch) - start )) "$status"' EXIT
"$KAIZEN_PLUGIN_ROOT/scripts/deploy.sh" "$stable" >/dev/null
"$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$stable"
state_set REVERT_PENDING 0
status=ok
