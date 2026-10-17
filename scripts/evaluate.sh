#!/usr/bin/env bash
# Compare fixed candidate samples against fresh samples of the stable bundle.
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
[ -n "$EXP" ] || die "no open experiment to evaluate"
stable=$(state_get STABLE_REV)
[ -f "$KAIZEN_DIR/stable-bundle.json" ] || die "capture the stable bundle first"
bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$KAIZEN_DIR/stable-bundle.json")
if [ $# -eq 0 ]; then
  set -- "$KAIZEN_DIR/baseline/$stable"/*.json -- "$EXP_DIR"/bench-candidate*.json
fi
python3 "$KAIZEN_PLUGIN_ROOT/scripts/measurement.py" evaluate "$EXP_DIR/decision.json" \
  "$stable" "$bundle" "$MIN_IMPROVEMENT_BP" "$MIN_SAMPLES" "$BASELINE_MAX_AGE_MINUTES" "$CORRECTNESS_ERROR_TYPES" "$@"
