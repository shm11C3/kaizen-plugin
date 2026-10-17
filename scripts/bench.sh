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
#   deploying anything but stable until recover.sh has run;
# - BENCH_PRECHECK_CMD (config.sh, optional) must succeed on every app host
#   before a sample is taken: a host busy with something else (an
#   unattended package upgrade, a leftover process) makes the sample noise,
#   and a refusal here is an infrastructure fact, not a sample.
# The benchmarker's exit code is never trusted; its result line is.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

label=${1:?usage: bench.sh <label> [--result 'pass=.. score=.. errors=..'] [--seconds N]}
shift
case "$label" in *[!A-Za-z0-9_-]*) die "label must be [A-Za-z0-9_-]" ;; esac
manual_result=""
manual_secs=0
requests=""
reserve_only=0
abandon=""
while [ $# -gt 0 ]; do
  case "$1" in
    --result) manual_result=${2:?--result needs 'pass=<true|false> score=<n> [errors=<text>]'}; shift 2 ;;
    --seconds) manual_secs=${2:?--seconds needs a number}; shift 2 ;;
    --requests) requests=${2:?--requests needs a count}; shift 2 ;;
    --reserve) reserve_only=1; shift ;;
    --abandon) abandon=${2:?--abandon needs a reason after confirming the portal run ended}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
if [ "$BENCH_MODE" = manual ] && [ -z "$manual_result$abandon" ] && [ "$reserve_only" = 0 ]; then
  die "BENCH_MODE=manual: bench.sh $label --reserve before starting the portal benchmark; then record --result"
fi
acquire_bench_lock
pending="$KAIZEN_DIR/manual-bench.json"
if [ -n "$abandon" ]; then
  [ -f "$pending" ] || die "no portal reservation to abandon"
  python3 - "$pending" "$label" <<'PY' || die "portal reservation label differs"
import json,sys
assert json.load(open(sys.argv[1]))['label']==sys.argv[2]
PY
  printf '%s\t%s\t%s\n' "$(now)" "$label" "$abandon" >> "$KAIZEN_DIR/abandoned-benchmarks.tsv"
  rm "$pending"
  echo "portal reservation abandoned; physical attempt remains counted"
  exit 0
fi
[ "$BENCH_MODE" = manual ] || { [ "$reserve_only" = 0 ] && [ -z "$manual_result" ] || die "reserve/result require manual mode"; }
[ "$reserve_only" = 0 ] || [ -z "$manual_result" ] || die "reserve and result are separate operations"
verify_bundle_config

deployed=$(state_get DEPLOYED_REV)
[ -n "$deployed" ] || die "nothing recorded as deployed; run deploy.sh first"
[ "$(state_get DEPLOYED_HEALTHY)" = 1 ] || die "the deployed app is not healthy; fix or recover before benchmarking"
[ "$(state_get REVERT_PENDING)" != 1 ] || die "resource recovery is incomplete; recover.sh must succeed before a benchmark"
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

budget_exp=${EXP:-$(state_get BENCH_BUDGET_EXPERIMENT)}
if [ -n "$budget_exp" ] && [ -z "$manual_result" ]; then
  started=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("startedAt",""))' "$KAIZEN_DIR/experiments/$budget_exp/manifest.json" 2>/dev/null || true)
  if [ -n "$started" ]; then
    age=$(( ( $(epoch) - $(to_epoch "$started") ) / 60 ))
    [ "$age" -lt "$MAX_EXP_MINUTES" ] || die "budget: $budget_exp is $age min old (MAX_EXP_MINUTES=$MAX_EXP_MINUTES); no new physical run"
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
if [ -n "${BENCH_PRECHECK_CMD:-}" ]; then
  for host in $APP_HOSTS; do
    remote "$host" "$BENCH_PRECHECK_CMD" >/dev/null 2>&1 || die "$host is not ready for a sample (BENCH_PRECHECK_CMD failed: $BENCH_PRECHECK_CMD); wait or fix the host, nothing recorded"
  done
fi
if [ "$BENCH_MODE" = ssh ] && [ -n "${BENCH_HOST_PRECHECK_CMD:-}" ]; then
  remote "$BENCH_HOST" "$BENCH_HOST_PRECHECK_CMD" >/dev/null 2>&1 || die "benchmark host precheck failed; no physical run started"
fi
candidate_run=1
case "$label" in baseline*) candidate_run=0; verify_bundle ;; esac
attempt=""
if [ "$BENCH_MODE" = manual ] && [ -n "$manual_result" ]; then
  [ -f "$pending" ] || die "reserve the portal run before starting it (bench.sh $label --reserve)"
  read -r out_dir base attempt < <(python3 - "$pending" "$label" "$deployed" "$EXP" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert (p['label'],p['revision'],p['experiment'])==tuple(sys.argv[2:]),'portal result differs from its reservation'
print(p['outDir'],p['base'],p['attempt'])
PY
  )
  [ -n "$attempt" ] || die "portal reservation mismatch"
else
  no_manual_bench
  reservation=$(python3 "$KAIZEN_PLUGIN_ROOT/scripts/measurement.py" reserve "$KAIZEN_DIR/bench-attempts.jsonl" \
    "$budget_exp" "$label" "$deployed" "$MAX_BENCH_PER_EXP" "$MAX_BENCH_TOTAL" "$MAX_BENCH_PER_HOUR" "$RECOVERY_BENCH_RESERVE" "$candidate_run") || die "physical benchmark budget exhausted"
  attempt=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$reservation")
fi
if [ "$reserve_only" = 1 ]; then
  python3 - "$pending" "$label" "$deployed" "$EXP" "$out_dir" "$base" "$attempt" <<'PY'
import json,sys
p,label,rev,exp,d,base,attempt=sys.argv[1:]
json.dump(dict(label=label,revision=rev,experiment=exp,outDir=d,base=base,attempt=attempt),open(p,'w'),indent=2)
PY
  echo "portal run $label reserved and counted; retain the environment reservation until result/abandon"
  exit 0
fi
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
  if declare -f parse_bench_requests >/dev/null; then requests=$(parse_bench_requests "$logfile"); fi
fi
case "$pass" in true|false) ;; *) die "result pass must be true or false" ;; esac
case "$score" in ''|*[!0-9]*) die "result score must be a nonnegative integer" ;; esac
case "$requests" in *[!0-9]*) die "requests must be a nonnegative integer" ;; esac
case "$label" in baseline*) verify_bundle ;; esac
[ "$pass" = true ] && passed=true || passed=false
# A sample taken while observe.sh has the slow log on carries the logging
# cost; it is kept as evidence but evaluate.sh leaves it out of the rule.
observed=$(state_get OBSERVE_SLOWLOG)
[ "$observed" = 1 ] || observed=0
[ ! -f "$KAIZEN_DIR/observation-active.json" ] || observed=1

bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$KAIZEN_DIR/stable-bundle.json")
fingerprints=$(resource_fingerprints)
python3 - "$out" "$label" "$deployed" "$EXP" "$passed" "$score" "${errors:-unknown}" "$secs" "$logfile" "$(now)" "$BENCH_MODE" "$observed" "$requests" "$bundle" "$fingerprints" "$attempt" "$KAIZEN_DIR/observation-active.json" "$(plugin_revision)" <<'EOF'
import json, sys
from pathlib import Path
out, label, rev, exp, passed, score, errors, secs, logfile, finished, mode, observed, requests, bundle, fingerprints, attempt, observation, plugin = sys.argv[1:]
json.dump({"label": label, "experiment": exp or None, "deployedRevision": rev,
           "pass": passed == "true", "score": int(score), "errors": errors,
           "durationSec": int(secs), "finishedAt": finished, "mode": mode, "log": logfile,
           "observed": observed == "1", "requests": int(requests) if requests else None,
           "observationSession": json.loads(Path(observation).read_text()) if Path(observation).exists() else None,
           "stableBundleId": bundle, "resourceFingerprints": dict(l.split('\t',1) for l in fingerprints.splitlines() if l),
           "physicalAttemptId": attempt, "pluginRevision": plugin},
          open(out, "w"), indent=2, ensure_ascii=False)
EOF
[ "$BENCH_MODE" != manual ] || rm "$pending"
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

echo "$label: pass=$passed score=$score errors=${errors:-unknown} (${secs}s on $(short "$deployed"))$([ "$observed" = 1 ] && echo ' [observed; not used by the rule]')"
if [ "$passed" != true ]; then
  if [ "$deployed" != "$stable" ]; then
    state_set REVERT_PENDING 1
    echo "the candidate failed correctness: recover.sh, then evaluate.sh and experiment.sh record"
  else
    echo "the stable revision failed correctness: the target itself is broken; fix that before any experiment"
  fi
  exit 1
fi
