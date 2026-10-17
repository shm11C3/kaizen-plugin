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
  *) die "usage: knowledge.sh match <dump> | ingest [<experiment-dir>] | stats" ;;
esac
