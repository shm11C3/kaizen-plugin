#!/usr/bin/env bash
# knowledge.sh match <observe-dump.txt>     patterns the evidence supports, ranked
# knowledge.sh ingest [<experiment-dir>]    append the closed experiment to its pattern's
#                                           Measured table and file record.json under records/
# knowledge.sh stats                        one line per pattern: measured rows, promotes
#
# The corpus lives in the plugin (KAIZEN_KNOWLEDGE_DIR, default
# <plugin>/knowledge) so every target feeds the same files. experiment.sh
# record calls `ingest` itself; running it again for the same experiment is
# a no-op.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KNOWLEDGE="${KAIZEN_KNOWLEDGE_DIR:-$KAIZEN_PLUGIN_ROOT/knowledge}"
cmd=${1:-}
shift || true

case "$cmd" in
  match)
    dump=${1:?knowledge.sh match <observe-dump.txt>}
    exec python3 "$KNOWLEDGE/match.py" "$dump"
    ;;
  stats)
    python3 - "$KNOWLEDGE" <<'EOF'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
for p in sorted((root / "patterns").glob("*.md")):
    text = p.read_text()
    stage = re.search(r"^stage:\s*(\S+)", text, re.M)
    rows = [l for l in re.search(r"## Measured\n(.*?)(?:\n## |\Z)", text, re.S).group(1).splitlines()
            if l.startswith("|") and not l.startswith("| problem") and not l.startswith("|---")] if "## Measured" in text else []
    promoted = sum(1 for l in rows if "| promote |" in l.replace("|  ", "| "))
    print(f"{p.stem:32} {stage.group(1) if stage else '?':8} measured={len(rows)} promoted={promoted}")
EOF
    ;;
  ingest)
    load_config
    dir=${1:-}
    if [ -z "$dir" ]; then
      [ -n "$EXP" ] && dir="$EXP_DIR" || die "no open experiment; give the experiment directory"
    fi
    [ -f "$dir/record.json" ] || die "$dir has no record.json (experiment.sh record first)"
    : "${PROBLEM:=unknown}"
    # Several loops (one per problem) share this corpus: serialize the append.
    for _ in $(seq 1 60); do mkdir "$KNOWLEDGE/.ingest.lock" 2>/dev/null && break; sleep 1; done
    [ -d "$KNOWLEDGE/.ingest.lock" ] || die "could not take $KNOWLEDGE/.ingest.lock"
    trap 'rmdir "$KNOWLEDGE/.ingest.lock" 2>/dev/null || true' EXIT
    python3 - "$KNOWLEDGE" "$dir" "$PROBLEM" <<'EOF'
import json, re, shutil, sys
from pathlib import Path
root, exp_dir, problem = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
record = json.load(open(exp_dir / "record.json"))
manifest = record["manifest"]
exp_id = record["experimentId"]
pattern = manifest.get("patternId") or re.sub(r"[^a-z0-9-]", "-", (manifest.get("hypothesisId") or "unclassified").lower())
dest = root / "records" / problem
dest.mkdir(parents=True, exist_ok=True)
copied = dest / f"{exp_id}.json"
if copied.exists():
    print(f"already ingested: {copied}")
    sys.exit(0)
shutil.copy(exp_dir / "record.json", copied)

rule = record["ruleDecision"]
base, cand = rule.get("baselineScores"), rule.get("candidateScores")
fmt = lambda s: "/".join(str(x) for x in s) if s else "-"
bp = rule.get("improvementBasisPoints")
delta = f"{bp / 100:+.0f}%" if bp is not None else "-"
samples = f"{len(base or [])}+{len(cand or [])}"
minutes = "-"
tl = record.get("timeline") or []
if len(tl) >= 2:
    from datetime import datetime
    t = lambda row: datetime.strptime(row.split("\t")[0], "%Y-%m-%dT%H:%M:%SZ")
    minutes = str(round((t(tl[-1]) - t(tl[0])).total_seconds() / 60))
errors = sorted({s.get("errors") for s in record.get("samples", []) if s.get("errors") not in (None, "none", "map[]")})
notes = ("; ".join(errors) if errors else "") + ((" | " if errors else "") + record["override"]["reason"] if record.get("override") else "")
row = f"| {problem} | {exp_id} | {fmt(base)} | {fmt(cand)} | {delta} | {samples} | {minutes} | {rule['decision']} | {record['finalDecision']} | {notes or '-'} |"

path = root / "patterns" / f"{pattern}.md"
if not path.exists():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
id: {pattern}
name: {pattern} (stub created by ingest; describe it)
stage: unknown
cost: ?
risk: ?
signature: none yet
sources: []
---
## Symptom

{manifest.get('observations', [{}])[0].get('summary', '')}

## Hypothesis template

{manifest.get('hypothesis', '')}

## Change template

{manifest.get('changeSummary', '')}

## Checklist

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups
""")
text = path.read_text()
marker = "## Measured\n"
head, _, tail = text.partition(marker)
table, _, rest = tail.partition("\n\n")
if "|---" not in table:
    table = "| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |\n|---|---|---|---|---|---|---|---|---|---|"
table = table.rstrip("\n") + "\n" + row
path.write_text(head + marker + table + "\n\n" + rest if rest else head + marker + table + "\n")

problems = root / "problems"
problems.mkdir(exist_ok=True)
pfile = problems / f"{problem}.md"
if not pfile.exists():
    pfile.write_text(f"# {problem}\n\nExperiments in the order they were run.\n\n| experiment | pattern | delta | final | reason |\n|---|---|---|---|---|\n")
with open(pfile, "a") as f:
    f.write(f"| {exp_id} | {pattern} | {delta} | {record['finalDecision']} | {record.get('reason', '')} |\n")
print(f"ingested {exp_id} -> {path.relative_to(root.parent)} ({pattern}), {copied.relative_to(root.parent)}")
EOF
    ;;
  plan)
    # plan [<observe dump>]: write .kaizen/plan.md: candidates ranked by
    # evidence strength x past promote rate / typical minutes, with the
    # columns the agent and the human fill (on the scoring path? order,
    # reason, stop condition). Everything under "## Notes" is preserved.
    load_config
    dump=${1:-}
    if [ -z "$dump" ]; then
      dump=$(ls -t "$EXP_DIR"/observe-*.txt "$KAIZEN_DIR"/observe-*.txt "$KAIZEN_DIR"/experiments/*/observe-*.txt 2>/dev/null | head -1)
    fi
    [ -n "$dump" ] && [ -f "$dump" ] || die "no observe dump; run observe.sh dump first"
    : "${TIME_BUDGET_MIN:=480}"
    [ -n "$(state_get LOOP_STARTED_AT)" ] || state_set LOOP_STARTED_AT "$(now)"
    python3 - "$KNOWLEDGE" "$dump" "$KAIZEN_DIR/plan.md" "$(state_get LOOP_STARTED_AT)" "$TIME_BUDGET_MIN" "$(state_get STABLE_REV)" "$(experiments_started_since $(( $(epoch) - 3600 )))" "$MAX_EXP_PER_HOUR" "$KAIZEN_DIR/log.md" <<'EOF'
import json, os, re, statistics, subprocess, sys
from datetime import datetime, timezone
root, dump, plan_path, started, budget_min, stable, exp_hour, max_hour, logmd = sys.argv[1:]
out = subprocess.run([sys.executable, f"{root}/match.py", dump, "--json"], capture_output=True, text=True, check=True).stdout
matches = json.loads(out)
def minutes(cost):
    nums = [int(x) for x in re.findall(r"\d+", cost or "")]
    return (sum(nums) / len(nums)) if nums else 30.0
rows = []
for m in matches:
    measured = m.get("measured") or []
    promoted = sum(1 for r in measured if r.get("final") == "promote")
    rate = (promoted + 1) / (len(measured) + 2)   # Laplace: unmeasured patterns start at 0.5
    prio = m["strength"] * rate / minutes(m["cost"]) * 60
    rows.append((prio, m, rate, measured))
rows.sort(key=lambda r: -r[0])
elapsed = (datetime.now(timezone.utc) - datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 60
done = set()
if os.path.exists(logmd):
    for line in open(logmd):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] not in ("closed", "---") and not cells[0].startswith("-"):
            done.add(cells[1])
notes = ""
if os.path.exists(plan_path):
    text = open(plan_path).read()
    if "## Notes" in text:
        notes = text[text.index("## Notes"):]
header = f"""# plan

- stable: {stable[:7] if stable else 'unset'}
- loop started: {started}; elapsed {elapsed:.0f} of {budget_min} min ({max(0, float(budget_min) - elapsed):.0f} left)
- experiments this hour: {exp_hour}/{max_hour}
- observation: {os.path.relpath(dump)}
- regenerated by knowledge.sh plan; edit the order, reason and stop columns, keep Notes

Fill `scoring path` from the manual (what the benchmark counts) before
ordering: a cheap fix off the scoring path is a wasted experiment.

| order | pattern | stage | priority | evidence | measured | scoring path? | reason | stop when |
|---|---|---|---|---|---|---|---|---|
"""
body = ""
for i, (prio, m, rate, measured) in enumerate(rows, 1):
    ev = (m["evidence"][0] if m["evidence"] else "")[:90].replace("|", "/")
    meas = f"{len(measured)} rows, {sum(1 for r in measured if r.get('final')=='promote')} promote" if measured else "none"
    body += f"| {i} | {m['id']} | {m['stage']} | {prio:.2f} | {ev} | {meas} | ? | | |\n"
if not rows:
    body += "| - | (no signature fired: read the dump and write the hypothesis by hand) | | | | | | | |\n"
footer = "\n" + (notes or "## Notes\n\n- closed experiments so far: " + (", ".join(sorted(done)) or "none") + "\n")
open(plan_path, "w").write(header + body + footer)
print(f"{plan_path}: {len(rows)} candidates ranked; fill 'scoring path?', 'reason', 'stop when'")
EOF
    ;;
  report)
    # Per problem: the outcome metrics the validation compares (time to first
    # promote, score at the end versus the first baseline). Human
    # interventions are counted by hand.
    python3 - "$KNOWLEDGE" <<'EOF'
import glob, json, os, statistics, sys
from datetime import datetime
root = sys.argv[1]
T = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
for pdir in sorted(glob.glob(f"{root}/records/*/")):
    problem = os.path.basename(pdir.rstrip("/"))
    recs = [json.load(open(f)) for f in glob.glob(pdir + "*.json")]
    recs = sorted((r for r in recs if "manifest" in r and "ruleDecision" in r), key=lambda r: r["manifest"].get("startedAt") or "")
    if not recs:
        continue
    first_base = final = first_promote = t0 = None
    minutes = 0
    for r in recs:
        m, rd = r["manifest"], r["ruleDecision"]
        if m.get("startedAt"):
            start = T(m["startedAt"]); t0 = t0 or start
            minutes += (T(r["closedAt"]) - start).total_seconds() / 60
        if first_base is None and rd.get("baselineScores"):
            first_base = statistics.median(rd["baselineScores"])
        if rd.get("candidateScores") and r["finalDecision"] == "promote":
            final = statistics.median(rd["candidateScores"])
            if first_promote is None and t0:
                first_promote = round((T(r["closedAt"]) - t0).total_seconds() / 60)
    counts = {d: sum(1 for r in recs if r["finalDecision"] == d) for d in ("promote", "reject", "inconclusive")}
    print(f"{problem}: {len(recs)} experiments ({counts['promote']} promote, {counts['reject']} reject, "
          f"{counts['inconclusive']} inconclusive), {round(minutes)} min in experiments, first promote at "
          f"{first_promote if first_promote is not None else '-'} min, first baseline median {first_base} -> "
          f"last promoted median {final if final is not None else '-'}")
    for r in recs:
        rd = r["ruleDecision"]
        print(f"  {r['experimentId']:36} {r['manifest'].get('patternId') or '-':28} "
              f"{rd.get('baselineScores')} -> {rd.get('candidateScores')} {r['finalDecision']}")
EOF
    ;;
  *) die "usage: knowledge.sh match <dump> | plan [<dump>] | ingest [<experiment-dir>] | stats | report" ;;
esac
