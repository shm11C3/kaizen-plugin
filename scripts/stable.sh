#!/usr/bin/env bash
# stable.sh repin [<ref>]      (default: the stable branch)
# Move STABLE_REV to a commit whose deployable content is identical to the
# current stable: the same trees under LOCAL_SYNC_PATHS and the overlays.
# This is what happens after `.kaizen/` records are committed on the stable
# branch: the branch moves, the servers do not. Without a repin the next
# experiment would branch from the old commit (and git would drop the
# tracked .kaizen files from the working tree) and a promote would refuse
# because the stable branch no longer points at STABLE_REV.
#
# The hosts keep running what they run; verify.sh proves the new revision
# matches them byte for byte, then only the markers, the state and the
# baseline samples (re-keyed, deployedRevision rewritten) change.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

cmd=${1:-}
shift || true
case "$cmd" in
  repin)
    ref=${1:-$STABLE_BRANCH}
    new=$(git_rev "$ref") || die "unknown revision $ref"
    old=$(state_get STABLE_REV)
    [ -n "$old" ] || die "STABLE_REV is not set; run /kaizen:setup"
    [ -z "$EXP" ] || die "experiment $EXP is open; record it before repinning stable"
    [ "$(state_get REVERT_PENDING)" != 1 ] || die "a failed candidate is still deployed; recover.sh first"
    if [ "$new" = "$old" ]; then echo "stable already $(short "$old")"; exit 0; fi
    paths="$LOCAL_SYNC_PATHS $OVERLAY_DIR"
    for host in $APP_HOSTS; do paths="$paths $OVERLAY_DIR-$host"; done
    for path in $paths; do
      a=$(git -C "$KAIZEN_PROJECT" rev-parse -q --verify "$old:$path" 2>/dev/null || true)
      b=$(git -C "$KAIZEN_PROJECT" rev-parse -q --verify "$new:$path" 2>/dev/null || true)
      [ "$a" = "$b" ] || die "$path differs between stable $(short "$old") and $ref $(short "$new"); that is a candidate, not a repin (experiment.sh new)"
    done
    "$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$new" >/dev/null || die "hosts do not match $ref; deploy.sh first"
    deployed=$(state_get DEPLOYED_REV)
    if [ "$deployed" = "$old" ]; then
      for host in $APP_HOSTS; do
        remote "$host" "echo $new | ${RSYNC_PATH:+sudo }tee $REMOTE_APP_DIR/.deployed-revision >/dev/null"
      done
      state_set DEPLOYED_REV "$new"
    fi
    state_set STABLE_REV "$new"
    moved=0
    if [ -d "$KAIZEN_DIR/baseline/$old" ]; then
      mkdir -p "$KAIZEN_DIR/baseline/$new"
      for f in "$KAIZEN_DIR/baseline/$old"/*.json; do
        [ -f "$f" ] || continue
        python3 - "$f" "$KAIZEN_DIR/baseline/$new/$(basename "$f")" "$old" "$new" <<'PY'
import json, sys
src, dst, old, new = sys.argv[1:]
s = json.load(open(src))
if s.get("deployedRevision") == old:
    s["deployedRevision"] = new
    s.setdefault("repinnedFrom", []).append(old)
json.dump(s, open(dst, "w"), indent=2, ensure_ascii=False)
PY
        rm -f "$f"
        moved=$((moved + 1))
      done
      rmdir "$KAIZEN_DIR/baseline/$old" 2>/dev/null || true
    fi
    record_step repin "$(short "$old")->$(short "$new")" 0 ok
    echo "stable repinned $(short "$old") -> $(short "$new") ($ref); $moved baseline samples re-keyed; hosts unchanged"
    ;;
  *) die "usage: stable.sh repin [<ref>]" ;;
esac
