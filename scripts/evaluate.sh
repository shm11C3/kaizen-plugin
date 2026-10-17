#!/usr/bin/env bash
# evaluate.sh                      compare .kaizen/baseline/<stable>/ with the
#                                  open experiment's bench-candidate*.json
# evaluate.sh <base.json>... -- <cand.json>...   explicit sample lists
#
# Fixed rule plugin-rule-v1, written to <experiment>/decision.json:
# correctness first and never offset by score; medians compared; promotion
# needs at least MIN_IMPROVEMENT_BP and noise separation (the worst candidate
# sample beats the best baseline sample). The agent reads this decision; it
# does not edit the file (the hook refuses), and an override is recorded
# separately by experiment.sh record --override.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

[ -n "$EXP" ] || die "no open experiment to evaluate"
stable=$(state_get STABLE_REV)

if [ $# -eq 0 ]; then
  set -- "$KAIZEN_DIR/baseline/$stable"/*.json -- "$EXP_DIR"/bench-candidate*.json
fi

python3 - "$EXP_DIR/decision.json" "$MIN_IMPROVEMENT_BP" "$stable" "$(now)" "$@" <<'PY'
import glob, json, os, statistics, sys

out_path, min_bp, stable, decided, *args = sys.argv[1:]
MIN_BP = int(min_bp)
if "--" not in args:
    sys.exit("usage: evaluate.sh [<baseline.json>... -- <candidate.json>...]")
split = args.index("--")

def load(paths):
    return [json.load(open(p)) for p in paths if os.path.exists(p)]

baseline = load(args[:split])
candidate = load(args[split + 1:])
baseline = [s for s in baseline if s.get("deployedRevision") == stable]

def passed(samples):
    return all(s.get("pass") for s in samples)

def scores(samples):
    return sorted(s["score"] for s in samples)

bp = None
if not baseline or not candidate:
    decision, reason = "inconclusive", f"need at least one baseline sample of stable {stable[:7]} and one candidate sample"
elif not passed(baseline):
    decision, reason = "inconclusive", "a baseline sample did not pass; no comparison basis"
elif not passed(candidate):
    decision, reason = "reject", "a candidate sample failed correctness (pass=false)"
else:
    b, c = scores(baseline), scores(candidate)
    bm, cm = statistics.median(b), statistics.median(c)
    bp = int((cm - bm) * 10000 // bm)
    if bp <= 0:
        decision, reason = "reject", f"candidate median {cm} does not beat baseline median {bm} ({bp} bp)"
    elif bp < MIN_BP:
        decision, reason = "inconclusive", f"improvement {bp} bp below {MIN_BP} bp; re-measure before deciding"
    elif c[0] <= b[-1]:
        decision, reason = "inconclusive", f"median improved {bp} bp but worst candidate {c[0]} does not clear best baseline {b[-1]}; noise not separated"
    else:
        decision, reason = "promote", f"median improved {bp} bp >= {MIN_BP} bp and worst candidate {c[0]} > best baseline {b[-1]}"

out = {
    "ruleVersion": "plugin-rule-v1",
    "minimumImprovementBasisPoints": MIN_BP,
    "decision": decision,
    "reason": reason,
    "improvementBasisPoints": bp,
    "baselineScores": scores(baseline) if baseline and passed(baseline) else None,
    "candidateScores": scores(candidate) if candidate and passed(candidate) else None,
    "baselineRevisions": sorted({s.get("deployedRevision") for s in baseline}),
    "candidateRevisions": sorted({s.get("deployedRevision") for s in candidate}),
    "decidedAt": decided,
}
json.dump(out, open(out_path, "w"), indent=2, ensure_ascii=False)
print(json.dumps(out, ensure_ascii=False))
PY
