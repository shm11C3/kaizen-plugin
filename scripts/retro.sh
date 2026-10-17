#!/usr/bin/env bash
# retro.sh list              unresolved friction entries, grouped, with ids
# retro.sh note <text>       add an observation by hand (a skill step that misled, a manual workaround)
# retro.sh resolve <id>... --fix <commit-or-note>   mark entries handled and log the fix in the plugin
# retro.sh count             one line: how many unresolved entries
#
# This is the plugin's self-improvement loop. lib.sh writes every refusal and
# unexpected failure to .kaizen/friction.jsonl; the retro skill turns them
# into script, skill, signature or checklist changes with a test, then marks
# them resolved here. Resolutions are appended to <plugin>/retro/log.md so
# the plugin carries the history of what real targets taught it.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FRICTION="$KAIZEN_DIR/friction.jsonl"
RETRO_LOG="${KAIZEN_RETRO_LOG:-$KAIZEN_PLUGIN_ROOT/retro/log.md}"
cmd=${1:-}
shift || true

case "$cmd" in
  count)
    n=$(python3 -c 'import json,sys
try: print(sum(1 for l in open(sys.argv[1]) if l.strip() and not json.loads(l).get("resolved")))
except FileNotFoundError: print(0)' "$FRICTION")
    echo "friction: $n unresolved entries (retro.sh list)"
    ;;
  list)
    python3 - "$FRICTION" <<'PY'
import json, sys
from collections import OrderedDict
try:
    lines = [l for l in open(sys.argv[1]) if l.strip()]
except FileNotFoundError:
    print("no friction recorded"); sys.exit(0)
groups = OrderedDict()
for i, l in enumerate(lines, 1):
    e = json.loads(l)
    if e.get("resolved"):
        continue
    key = (e["script"], e["kind"], e["message"])
    groups.setdefault(key, []).append((i, e))
if not groups:
    print("no unresolved friction"); sys.exit(0)
for (script, kind, message), items in groups.items():
    ids = ",".join(str(i) for i, _ in items)
    first = items[0][1]
    print(f"[{ids}] {script} {kind} x{len(items)}: {message}")
    if first.get("command"):
        print(f"      command: {first['command']}")
    print(f"      first {first['ts']} exp={first.get('experiment')}")
PY
    ;;
  note)
    [ $# -gt 0 ] || die "retro.sh note <text>"
    load_config 2>/dev/null || true
    friction_log note "$*"
    echo "noted"
    ;;
  resolve)
    ids=()
    fix=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --fix) fix=${2:?--fix needs a commit sha or a short note}; shift 2 ;;
        *) ids+=("$1"); shift ;;
      esac
    done
    [ ${#ids[@]} -gt 0 ] && [ -n "$fix" ] || die "retro.sh resolve <id>... --fix <commit-or-note>"
    mkdir -p "$(dirname "$RETRO_LOG")"
    [ -f "$RETRO_LOG" ] || printf '# retro log\n\nWhat real targets taught the plugin, one row per resolved friction group.\n\n| when | problem | script | message | fix |\n|---|---|---|---|---|\n' > "$RETRO_LOG"
    python3 - "$FRICTION" "$RETRO_LOG" "$fix" "$(now)" "${PROBLEM:-$(sed -n 's/^PROBLEM=//p' "$KAIZEN_DIR/config.sh" 2>/dev/null | head -1)}" "${ids[@]}" <<'PY'
import json, sys
path, log, fix, ts, problem, *ids = sys.argv[1:]
ids = {int(i) for i in ids}
lines = [l for l in open(path) if l.strip()]
out, rows = [], []
for i, l in enumerate(lines, 1):
    e = json.loads(l)
    if i in ids and not e.get("resolved"):
        e["resolved"] = True; e["fix"] = fix; e["resolvedAt"] = ts
        rows.append(f"| {ts} | {problem or '-'} | {e['script']} | {e['message'][:80]} | {fix} |")
    out.append(json.dumps(e, ensure_ascii=False))
open(path, "w").write("\n".join(out) + "\n")
with open(log, "a") as f:
    f.write("\n".join(rows) + ("\n" if rows else ""))
print(f"resolved {len(rows)} entries -> {log}")
PY
    ;;
  *) die "usage: retro.sh list | note <text> | resolve <id>... --fix <commit-or-note> | count" ;;
esac
