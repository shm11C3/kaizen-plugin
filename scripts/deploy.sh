#!/usr/bin/env bash
# deploy.sh <git-ref>
# Export one committed revision and, on every host in APP_HOSTS: push the
# application directories and the etc/ overlay, restart the services whose
# configuration changed, build, restart the application, wait for health,
# write the deployed-revision marker, and verify the host matches the ref
# byte for byte. Prints the deployed revision. Fails closed: any step failing
# leaves a "failed" timeline row, a non-zero exit, and DEPLOYED_HEALTHY=0.
#
# Only committed revisions deploy, so every benchmark is tied to a SHA. While
# a failed candidate is still deployed (REVERT_PENDING=1) only the stable
# revision may be deployed: a broken target goes back to stable first. A
# non-stable revision deploys only inside an open experiment whose manifest
# names a hypothesis, its evidence, and the expected effect.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

ref=${1:?usage: deploy.sh <git-ref>}
[ $# -eq 1 ] || die "usage: deploy.sh <git-ref> (one committed revision, nothing else)"
rev=$(git_rev "$ref") || die "unknown revision $ref"
stable=$(state_get STABLE_REV)
if [ "$(state_get REVERT_PENDING)" = 1 ] && [ "$rev" != "$stable" ]; then
  die "the last candidate failed and is still deployed; run recover.sh first"
fi
if [ "$rev" != "$stable" ]; then
  [ -n "$EXP" ] || die "no open experiment; a non-stable revision deploys only inside one (experiment.sh new <slug>)"
  python3 - "$EXP_DIR/manifest.json" <<'EOF' || die "fill $EXP_DIR/manifest.json (hypothesis, observations[0].artifact, expectedEffect) before deploying a candidate"
import json, sys
m = json.load(open(sys.argv[1]))
ok = m.get("hypothesis") and m.get("expectedEffect") and m.get("observations") and m["observations"][0].get("artifact")
sys.exit(0 if ok else 1)
EOF
fi

acquire_bench_lock
start=$(epoch)
status=failed
export_dir=""
trap 'record_step deploy "$ref" $(( $(epoch) - start )) "$status"; rmdir "$LOCK_DIR" 2>/dev/null || true; [ -n "$export_dir" ] && rm -rf "$export_dir"' EXIT

export_dir=$(mktemp -d "${TMPDIR:-/tmp}/kaizen-deploy.XXXXXX")
git -C "$KAIZEN_PROJECT" archive "$rev" | tar -x -C "$export_dir"
for path in $LOCAL_SYNC_PATHS; do
  [ -d "$export_dir/$path" ] || die "$path is not a directory in $ref (LOCAL_SYNC_PATHS)"
done

# restart_overlay_services <host> <changed-paths>: the service mapped to each
# top-level overlay directory that changed restarts before the application.
restart_overlay_services() {
  local host=$1 changed=$2 top pair service
  [ -n "$changed" ] || return 0
  log "$host overlay changed: $(echo "$changed" | tr '\n' ' ')"
  for top in $(echo "$changed" | cut -d/ -f1 | sort -u); do
    for pair in $OVERLAY_SERVICES; do
      [ "${pair%%:*}" = "$top" ] || continue
      service=${pair#*:}
      if [ "$service" = daemon-reload ]; then
        remote "$host" "sudo systemctl daemon-reload"
      else
        log "$host restart $service"
        remote "$host" "sudo systemctl restart $service"
      fi
    done
  done
}

state_set DEPLOYED_REV "$rev"
state_set DEPLOYED_AT "$(now)"
state_set DEPLOYED_HEALTHY 0
for host in $APP_HOSTS; do
  log "deploy $(short "$rev") ($ref) -> $host"
  for path in $LOCAL_SYNC_PATHS; do
    sync_dir "$export_dir/$path" "$host" "$REMOTE_APP_DIR/$path"
  done
  changed=""
  if [ -d "$export_dir/$OVERLAY_DIR" ]; then
    changed=$(sync_overlay "$export_dir/$OVERLAY_DIR" "$host")
  fi
  if [ -d "$export_dir/$OVERLAY_DIR-$host" ]; then
    changed="$changed
$(sync_overlay "$export_dir/$OVERLAY_DIR-$host" "$host")"
  fi
  restart_overlay_services "$host" "$(echo "$changed" | sed '/^$/d')"
  log "$host build"
  remote "$host" "$BUILD_CMD"
  log "$host restart"
  remote "$host" "$RESTART_CMD"
  healthy=0
  for _ in $(seq 1 "$HEALTH_RETRIES"); do
    if remote "$host" "$HEALTH_CMD" >/dev/null 2>&1; then healthy=1; break; fi
    sleep 1
  done
  [ "$healthy" = 1 ] || die "$host did not become healthy after $HEALTH_RETRIES tries; check the service log there"
  remote "$host" "echo $rev | ${RSYNC_PATH:+sudo }tee $REMOTE_APP_DIR/.deployed-revision >/dev/null"
done

"$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$rev" >/dev/null
state_set DEPLOYED_HEALTHY 1
[ "$rev" = "$stable" ] && state_set REVERT_PENDING 0
status=ok
echo "$rev"
