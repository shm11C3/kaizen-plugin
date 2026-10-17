#!/usr/bin/env bash
# bench.sh <label>                                   BENCH_MODE=ssh (practice)
# bench.sh <label> --result 'pass=true score=1234 errors=...' [--seconds N]
#                                                    BENCH_MODE=manual (contest)
# One benchmark sample against what is deployed, saved next to the experiment
# as bench-<label>.json (pass, score, errors, duration, deployed revision)
# plus the raw log bench-<label>.log. In manual mode the operator runs the
# benchmark on the contest portal and passes the portal's result here, so
# the record keeps the same shape. Labels starting with "baseline" measure
# the stable revision and are also filed under .kaizen/baseline/<rev>/ so
# later experiments reuse them until the next promotion.
#
# Enforced here so the agent does not have to remember:
# - one benchmark or deploy at a time (directory lock);
# - what every host runs is what state.env says is deployed (marker check);
# - a candidate label needs an open experiment and at least one baseline
#   sample of the current stable revision;
# - at most MAX_BENCH_PER_EXP samples and MAX_EXP_MINUTES per experiment;
# - a candidate that fails correctness sets REVERT_PENDING, which blocks
#   deploying anything but stable until recover.sh has run.
# The benchmarker's exit code is never trusted; its result line is.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

label=${1:?usage: bench.sh <label> [--result 'pass=.. score=.. errors=..'] [--seconds N]}
shift
case "$label" in *[!A-Za-z0-9_-]*) die "label must be [A-Za-z0-9_-]" ;; esac
manual_result=""
manual_secs=0
while [ $# -gt 0 ]; do
  case "$1" in
    --result) manual_result=${2:?--result needs 'pass=<true|false> score=<n> [errors=<text>]'}; shift 2 ;;
    --seconds) manual_secs=${2:?--seconds needs a number}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
if [ "$BENCH_MODE" = manual ] && [ -z "$manual_result" ]; then
  die "BENCH_MODE=manual: run the benchmark on the portal, then bench.sh $label --result 'pass=true score=1234 errors=none'"
fi

deployed=$(state_get DEPLOYED_REV)
[ -n "$deployed" ] || die "nothing recorded as deployed; run deploy.sh first"
[ "$(state_get DEPLOYED_HEALTHY)" = 1 ] || die "the deployed app is not healthy; fix or recover before benchmarking"
stable=$(state_get STABLE_REV)
for host in $APP_HOSTS; do
  marker=$(deployed_marker "$host")
  [ "$marker" = "$deployed" ] || die "$host runs $(short "$marker") but state says $(short "$deployed"); deploy again"
done

case "$label" in
  baseline*)
    [ "$deployed" = "$stable" ] || die "a baseline sample must measure the stable revision $(short "$stable"), but $(short "$deployed") is deployed"
    ;;
  *)
    [ -n "$EXP" ] || die "no open experiment; candidate samples belong to one (experiment.sh new <slug>)"
    [ "$deployed" != "$stable" ] || die "the stable revision is deployed; a candidate sample needs the candidate deployed"
    ls "$KAIZEN_DIR/baseline/$stable"/*.json >/dev/null 2>&1 || die "no baseline sample for stable $(short "$stable"); run bench.sh baseline first"
    ;;
esac

if [ -n "$EXP" ]; then
  count=$(count_matches "$EXP_DIR"/bench-*.json)
  [ "$count" -lt "$MAX_BENCH_PER_EXP" ] || die "budget: $EXP already has $count samples (MAX_BENCH_PER_EXP=$MAX_BENCH_PER_EXP); evaluate with what you have"
  started=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("startedAt",""))' "$EXP_DIR/manifest.json" 2>/dev/null || true)
  if [ -n "$started" ]; then
    age=$(( ( $(epoch) - $(to_epoch "$started") ) / 60 ))
    [ "$age" -lt "$MAX_EXP_MINUTES" ] || die "budget: $EXP has been open $age min (MAX_EXP_MINUTES=$MAX_EXP_MINUTES); evaluate and record it"
  fi
fi
# Samples of the stable revision taken outside an experiment go straight to
# .kaizen/baseline/<stable>/ with a timestamp, so the same label works again
# after every promotion; inside an experiment the label is the file name.
if [ -n "$EXP" ]; then
  out_dir=$EXP_DIR; base="bench-$label"
else
  out_dir="$KAIZEN_DIR/baseline/$stable"; base="bench-$(stamp)-$label"
  mkdir -p "$out_dir"
fi
[ ! -e "$out_dir/$base.json" ] || die "$out_dir/$base.json exists; use a new label"

acquire_bench_lock
logfile="$out_dir/$base.log"
out="$out_dir/$base.json"
if [ "$BENCH_MODE" = manual ]; then
  printf 'manual result recorded %s\n%s\n' "$(now)" "$manual_result" > "$logfile"
  secs=$manual_secs
  pass=$(printf '%s' "$manual_result" | sed -n 's/.*pass=\([a-z]*\).*/\1/p')
  score=$(printf '%s' "$manual_result" | sed -n 's/.*score=\([0-9]*\).*/\1/p')
  errors=$(printf '%s' "$manual_result" | sed -n 's/.*errors=\(.*\)$/\1/p' | tr ' ' ',')
  [ -n "$pass" ] && [ -n "$score" ] || die "--result must contain pass=<true|false> and score=<n>"
else
  log "bench $label on $(short "$deployed") via $BENCH_HOST; log $logfile"
  start=$(epoch)
  remote "$BENCH_HOST" "$(bench_command)" > "$logfile" 2>&1 || true
  secs=$(( $(epoch) - start ))
  if ! result=$(parse_bench "$logfile"); then
    record_step bench "$label" "$secs" "no-result"
    tail -5 "$logfile" >&2
    die "no result line in $logfile; an infrastructure failure, not a verdict (nothing recorded as a sample)"
  fi
  read -r pass score errors <<<"$result"
fi
[ "$pass" = true ] && passed=true || passed=false

python3 - "$out" "$label" "$deployed" "$EXP" "$passed" "$score" "${errors:-none}" "$secs" "$logfile" "$(now)" "$BENCH_MODE" <<'EOF'
import json, sys
out, label, rev, exp, passed, score, errors, secs, logfile, finished, mode = sys.argv[1:]
json.dump({"label": label, "experiment": exp or None, "deployedRevision": rev,
           "pass": passed == "true", "score": int(score), "errors": errors,
           "durationSec": int(secs), "finishedAt": finished, "mode": mode, "log": logfile},
          open(out, "w"), indent=2, ensure_ascii=False)
EOF
record_step bench "$label" "$secs" "pass=$passed score=$score"
state_set LAST_RUN "$label"
state_set LAST_PASS "$passed"
state_set LAST_SCORE "$score"

case "$label" in baseline*)
  if [ -n "$EXP" ]; then
    mkdir -p "$KAIZEN_DIR/baseline/$stable"
    cp "$out" "$KAIZEN_DIR/baseline/$stable/bench-$(stamp)-$label.json"
  fi
  ;;
esac

echo "$label: pass=$passed score=$score errors=${errors:-none} (${secs}s on $(short "$deployed"))"
if [ "$passed" != true ]; then
  if [ "$deployed" != "$stable" ]; then
    state_set REVERT_PENDING 1
    echo "the candidate failed correctness: recover.sh, then evaluate.sh and experiment.sh record"
  else
    echo "the stable revision failed correctness: the target itself is broken; fix that before any experiment"
  fi
  exit 1
fi
