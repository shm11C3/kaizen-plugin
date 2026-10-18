#!/usr/bin/env bash
# status.sh: where the loop stands, in one screen.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

stable=$(state_get STABLE_REV)
echo "project      $KAIZEN_PROJECT"
echo "stable       ${stable:-unset} (branch $STABLE_BRANCH)"
echo "deployed     $(state_get DEPLOYED_REV) healthy=$(state_get DEPLOYED_HEALTHY) at $(state_get DEPLOYED_AT)"
echo "revert       pending=$(state_get REVERT_PENDING)"
echo "experiment   ${EXP:-none}"
if [ -n "$EXP" ]; then
  echo "  samples    $(count_matches "$EXP_DIR"/bench-*.json)/$(count_limit_label "$MAX_BENCH_PER_EXP") (recorded samples; caps count physical attempts)"
  [ -f "$EXP_DIR/decision.json" ] && echo "  decision   $(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["decision"], "-", d["reason"])' "$EXP_DIR/decision.json")"
fi
echo "last run     $(state_get LAST_RUN) pass=$(state_get LAST_PASS) score=$(state_get LAST_SCORE)"
python3 "$KAIZEN_PLUGIN_ROOT/scripts/measurement.py" summary "$KAIZEN_DIR/bench-attempts.jsonl"
[ ! -f "$KAIZEN_DIR/manual-bench.json" ] || echo "portal       RESERVED: finish or abandon after confirming the run ended"
python3 "$KAIZEN_PLUGIN_ROOT/scripts/strategy.py" --project "$KAIZEN_PROJECT" status
echo "run limits   total $(count_limit_label "$MAX_BENCH_TOTAL"); hourly $(count_limit_label "$MAX_BENCH_PER_HOUR"); stable/recovery reserve $RECOVERY_BENCH_RESERVE within each finite cap"
if [ -n "$stable" ] && ls "$KAIZEN_DIR/baseline/$stable"/*.json >/dev/null 2>&1; then
  python3 - "$KAIZEN_DIR/baseline/$stable" <<'EOF'
import glob, json, statistics, sys
s = sorted(json.load(open(p))["score"] for p in glob.glob(sys.argv[1] + "/*.json"))
print(f"baseline     {len(s)} samples median {statistics.median(s)} range {s[0]}-{s[-1]}")
EOF
else
  echo "baseline     none for this stable (bench.sh baseline)"
fi
echo "budget       $(experiments_started_since $(( $(epoch) - 3600 )))/$(count_limit_label "$MAX_EXP_PER_HOUR") experiments this hour; $(count_limit_label "$MAX_BENCH_PER_EXP") physical runs and $MAX_EXP_MINUTES min per experiment"
[ -d "$LOCK_DIR" ] && echo "lock         HELD ($LOCK_DIR)"
if [ -f "$KAIZEN_DIR/log.md" ]; then
  echo
  tail -6 "$KAIZEN_DIR/log.md"
fi
