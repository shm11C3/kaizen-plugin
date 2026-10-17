#!/usr/bin/env bash
# stable.sh repin [<ref>]      (default: the stable branch)
# stable.sh forget-baseline <reason>
#   Retire every baseline sample of the current stable revision: they are
#   moved to .kaizen/baseline/<rev>.retired-<stamp>/ with the reason, so the
#   next bench.sh baseline starts a clean set. For samples that measured
#   something other than the application (a package upgrade eating a core,
#   a MySQL restart mid-run); the files stay as evidence, out of evaluate.sh.
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
  capture)
    [ -z "$EXP" ] || die "capture stable resources before opening an experiment"
    acquire_bench_lock
    no_manual_bench
    stable=$(state_get STABLE_REV)
    [ -n "$stable" ] && [ "$(state_get DEPLOYED_REV)" = "$stable" ] && [ "$(state_get DEPLOYED_HEALTHY)" = 1 ] || die "deploy healthy stable before capture"
    [ "$(state_get REVERT_PENDING)" != 1 ] || die "recover before capture; never bless a failed candidate"
    "$KAIZEN_PLUGIN_ROOT/scripts/verify.sh" "$stable" >/dev/null
    [ -f "$KAIZEN_DIR/.gitignore" ] || printf '*\n!.gitignore\n!config.sh\n!preset.sh\n!RULES.md\n' > "$KAIZEN_DIR/.gitignore"
    previous=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$KAIZEN_DIR/stable-bundle.json" 2>/dev/null || true)
    identity=$(capture_bundle) || die "stable bundle capture failed"
    if [ "$identity" != "$previous" ]; then
      if [ -d "$KAIZEN_DIR/baseline/$stable" ]; then
        mv "$KAIZEN_DIR/baseline/$stable" "$KAIZEN_DIR/baseline/$stable.retired-$(stamp)-$RANDOM"
      fi
      state_set BENCH_BUDGET_EXPERIMENT ""
    fi
    echo "stable bundle $identity captured; verify schema/config restoration with recover.sh before experiments"
    ;;
  repin)
    acquire_bench_lock
    no_manual_bench
    verify_bundle
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
    config_hash=$(config_digest) || die "cannot identify target configuration"
    fingerprints=$(resource_fingerprints) || die "cannot probe stable resources"
    deployed=$(state_get DEPLOYED_REV)
    if [ "$deployed" = "$old" ]; then
      for host in $APP_HOSTS; do
        remote "$host" "echo $new | ${RSYNC_PATH:+sudo }tee $REMOTE_APP_DIR/.deployed-revision >/dev/null"
      done
      state_set DEPLOYED_REV "$new"
    fi
    state_set STABLE_REV "$new"
    python3 "$KAIZEN_PLUGIN_ROOT/scripts/resources.py" repin "$KAIZEN_DIR/stable-bundle.json" \
      "$new" "$config_hash" "$fingerprints"
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
  forget-baseline)
    reason=${*:-}
    [ -n "$reason" ] || die "stable.sh forget-baseline <reason>"
    [ -z "$EXP" ] || die "experiment $EXP is open; record it first"
    stable=$(state_get STABLE_REV)
    [ -n "$stable" ] || die "STABLE_REV is not set"
    dir="$KAIZEN_DIR/baseline/$stable"
    ls "$dir"/*.json >/dev/null 2>&1 || die "no baseline sample for stable $(short "$stable")"
    retired="$dir.retired-$(stamp)"
    mv "$dir" "$retired"
    printf '%s\t%s\n' "$(now)" "$reason" > "$retired/REASON.txt"
    n=$(count_matches "$retired"/*.json)
    record_step forget-baseline "$(short "$stable")" 0 "$n samples: $reason"
    echo "retired $n baseline samples of $(short "$stable") -> $retired; take a new baseline (bench.sh baseline)"
    ;;
  *) die "usage: stable.sh capture | repin [<ref>] | forget-baseline <reason>" ;;
esac
