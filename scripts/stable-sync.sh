#!/usr/bin/env bash
# Synchronize one idle sandbox to proven competition stable; never invent adoption.
set -euo pipefail
[ "${KAIZEN_TEAM_MODE:-}" = 1 ] && [ "${KAIZEN_SANDBOX_SYNC:-}" = 1 ] \
  || { echo 'stable-sync requires an owned sandbox target action' >&2; exit 2; }
export KAIZEN_SYNC_ACTIVE=1
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
pending="$KAIZEN_DIR/stable-sync-pending.json"
[ -z "$EXP" ] || die "close the sandbox experiment before sync"
no_manual_bench
[ ! -d "$LOCK_DIR" ] || die "a sandbox operation is still running"

field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$pending" "$1"; }
sync_health() {
  local host attempt healthy
  for host in $APP_HOSTS; do
    healthy=0
    for attempt in $(seq 1 "$HEALTH_RETRIES"); do
      if remote "$host" "$HEALTH_CMD" >/dev/null 2>&1; then healthy=1; break; fi
      sleep 1
    done
    [ "$healthy" = 1 ] || return 1
  done
}
sync_status() {
  python3 - "$pending" "$1" <<'PY'
import datetime,json,sys
from pathlib import Path
p=Path(sys.argv[1]); data=json.loads(p.read_text()); data['status']=sys.argv[2]
instant=datetime.datetime.now(datetime.timezone.utc)
data['updatedAt']=instant.isoformat()
data.setdefault('steps',[]).append({'status':sys.argv[2],'at':instant.isoformat()})
data['durationSeconds']=(instant-datetime.datetime.fromisoformat(data['startedAt'])).total_seconds()
for destination in (p,Path(data['history'])/'sync.json'):
    temporary=destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n'); temporary.replace(destination)
PY
}
rollback() {
  local old history branch_before current
  old=$(field oldStable); history=$(field history); branch_before=$(field branchBefore)
  cp "$history/bundle-before.json" "$KAIZEN_DIR/stable-bundle.json" || return 1
  state_set STABLE_REV "$old" || return 1
  state_set REVERT_PENDING 1 || return 1
  "$KAIZEN_PLUGIN_ROOT/scripts/recover.sh" >"$history/rollback.log" 2>&1 || return 1
  sync_health || return 1
  current=$(git_rev "$STABLE_BRANCH") || return 1
  git -C "$KAIZEN_PROJECT" switch -q --detach "$branch_before" || return 1
  if [ "$current" != "$branch_before" ]; then
    [ "$current" = "$(field targetRevision)" ] || return 1
    git -C "$KAIZEN_PROJECT" update-ref "refs/heads/$STABLE_BRANCH" "$branch_before" "$current" || return 1
  fi
  git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH" || return 1
  sync_status rolled-back || return 1
  rm -f "$pending" || return 1
  return 0
}
if [ "${1:-}" = --rollback ]; then
  [ "$#" = 1 ] && [ -f "$pending" ] || die "no pending sync to roll back"
  if rollback; then echo 'previous sandbox stable restored and verified; take fresh baseline'; exit 0; fi
  sync_status recovery-pending
  die "sandbox sync recovery is pending; inspect its rollback log before retrying"
fi
[ "$#" = 2 ] && [ "$1" = --record ] && [ -n "${KAIZEN_SYNC_PROOF:-}" ] || die "use target stable-sync --record <official record.json>"
[ ! -f "$pending" ] || die "previous sync pending; use --rollback"
[ "$(state_get REVERT_PENDING)" != 1 ] || die "recover the sandbox before syncing"
old=$(state_get STABLE_REV)
[ -n "$old" ] && [ "$(state_get DEPLOYED_REV)" = "$old" ] && [ "$(state_get DEPLOYED_HEALTHY)" = 1 ] \
  || die "sync starts from healthy deployed sandbox stable"
verify_bundle
"$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$old" >/dev/null
git_dirty && die "commit sandbox source changes before syncing"
[ "$(git -C "$KAIZEN_PROJECT" symbolic-ref --short HEAD)" = "$STABLE_BRANCH" ] || die "switch to the sandbox stable branch before sync"
new=$(python3 -c 'import json,os;print(json.loads(os.environ["KAIZEN_SYNC_PROOF"])["targetRevision"])')
promoted=$(python3 -c 'import json,os;print(json.loads(os.environ["KAIZEN_SYNC_PROOF"])["promotedRevision"])')
# A metadata repin after the official adoption may change SHA, never deployable trees.
# shellcheck disable=SC2086
git -C "$KAIZEN_PROJECT" diff --quiet "$promoted" "$new" -- $LOCAL_SYNC_PATHS "$OVERLAY_DIR" ":(glob)$OVERLAY_DIR-*" \
  || die "official stable has newer deployable content; select its adoption record"
if [ "$new" = "$old" ]; then
  sync_health || die "the unchanged sandbox stable is unhealthy; recover before syncing"
  python3 - "$KAIZEN_DIR" <<'PY'
import datetime,json,os,sys,uuid
from pathlib import Path
history=Path(sys.argv[1])/'stable-syncs'/uuid.uuid4().hex; history.mkdir(parents=True)
data=dict(json.loads(os.environ['KAIZEN_SYNC_PROOF']),status='verified-unchanged',
          baselineAction='preserved',verifiedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
(history/'sync.json').write_text(json.dumps(data,indent=2)+'\n')
PY
  echo 'sandbox already has the adopted stable; verified without changing baseline'
  exit 0
fi
branch_before=$(git_rev "$STABLE_BRANCH")
git -C "$KAIZEN_PROJECT" merge-base --is-ancestor "$branch_before" "$new" || die "sandbox stable branch cannot fast-forward to official source"
git -C "$KAIZEN_PROJECT" diff --quiet "$branch_before" "$new" -- .kaizen || die "official source would replace sandbox loop configuration"
# shellcheck disable=SC2086
changed_resources=$(git -C "$KAIZEN_PROJECT" diff --name-only "$old" "$new" -- $RESOURCE_PATHS ":(glob)$OVERLAY_DIR-*")
[ -z "$changed_resources" ] || [ -n "$RECOVERY_CMD" ] || die "resource changes need a configured initialization/recovery command"
export KAIZEN_SYNC_OLD="$old" KAIZEN_SYNC_BRANCH="$branch_before" KAIZEN_SYNC_NEW="$new"
python3 - "$KAIZEN_DIR" <<'PY'
import datetime,json,os,shutil,sys,uuid
from pathlib import Path
root=Path(sys.argv[1]); key=uuid.uuid4().hex; history=root/'stable-syncs'/key; history.mkdir(parents=True)
shutil.copy2(root/'stable-bundle.json',history/'bundle-before.json')
shutil.copy2(root/'state.env',history/'state-before.txt')
data=dict(json.loads(os.environ['KAIZEN_SYNC_PROOF']),id=key,history=str(history),status='prepared',
          oldStable=os.environ['KAIZEN_SYNC_OLD'],branchBefore=os.environ['KAIZEN_SYNC_BRANCH'],
          startedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
temporary=root/'stable-sync-pending.tmp'; temporary.write_text(json.dumps(data,indent=2)+'\n')
temporary.replace(root/'stable-sync-pending.json')
(history/'sync.json').write_text(json.dumps(data,indent=2)+'\n')
for revision in {data['oldStable'],data['targetRevision']}:
    base=root/'baseline'/revision
    if base.exists():
        base.rename(base.with_name(revision+'.retired-sync-'+key))
PY
history=$(field history)
on_exit() {
  local code=$?
  trap - EXIT
  if [ -f "$pending" ]; then
    if rollback; then
      echo 'sync failed; previous sandbox stable restored and verified; fresh baseline required' >&2
    else
      sync_status recovery-pending
      echo 'sync failed and rollback remains pending; use target stable-sync --rollback' >&2
    fi
    [ "$code" != 0 ] || code=2
  fi
  exit "$code"
}
trap on_exit EXIT
sync_status deploying
state_set STABLE_REV "$new"
state_set REVERT_PENDING 1
"$KAIZEN_PLUGIN_ROOT/scripts/deploy.sh" "$new" >"$history/deploy.log" 2>&1
sync_status initializing-resources
if [ -n "$RECOVERY_CMD" ]; then
  for host in $RESOURCE_HOSTS; do remote "$host" "$RECOVERY_CMD" >>"$history/deploy.log" 2>&1; done
fi
sync_health
"$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$new" >>"$history/deploy.log" 2>&1
state_set REVERT_PENDING 0
"$KAIZEN_PLUGIN_ROOT/scripts/stable.sh" capture >>"$history/deploy.log" 2>&1
"$KAIZEN_PLUGIN_ROOT/scripts/recover.sh" >>"$history/deploy.log" 2>&1
sync_health
sync_status committing
git -C "$KAIZEN_PROJECT" switch -q --detach "$new"
git -C "$KAIZEN_PROJECT" update-ref "refs/heads/$STABLE_BRANCH" "$new" "$branch_before"
git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH"
state_set BENCH_BUDGET_EXPERIMENT ''
sync_status completed
rm -f "$pending"
record_step stable-sync "$old->$new" 0 ok
echo "sandbox stable synced to $new; take new baseline samples in this sandbox"
