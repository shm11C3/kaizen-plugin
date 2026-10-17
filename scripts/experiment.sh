#!/usr/bin/env bash
# experiment.sh new <slug>
# experiment.sh record [--override <promote|reject|inconclusive>] <reason...>
# experiment.sh current
#
# One experiment = one hypothesis = one branch exp/NNN-<slug> = one directory
# .kaizen/experiments/NNN-<slug>/. `new` writes the manifest template (the
# kaizen-agent Candidate Manifest fields) and opens the branch from stable.
# `record` closes it: the rule's decision comes from decision.json; the agent
# or the human may override it, and the override and its reason are written
# into record.json next to the rule's own verdict. promote fast-forwards the
# stable branch, makes the candidate the new STABLE_REV, and reseeds
# .kaizen/baseline/ from the candidate samples; anything else recovers stable.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

cmd=${1:-}
shift || true

case "$cmd" in
  new)
    slug=${1:?experiment.sh new <slug>}
    case "$slug" in *[!A-Za-z0-9_-]*) die "slug must be [A-Za-z0-9_-]" ;; esac
    [ -z "$EXP" ] || die "experiment $EXP is still open; record its decision first"
    [ "$(state_get REVERT_PENDING)" != 1 ] || die "a failed candidate is still deployed; recover.sh first"
    git_dirty && die "the working tree has uncommitted changes; commit or stash them before a new experiment"
    stable=$(state_get STABLE_REV)
    [ -n "$stable" ] || die "STABLE_REV is not set; run /kaizen:setup"
    recent=$(experiments_started_since $(( $(epoch) - 3600 )))
    [ "$recent" -lt "$MAX_EXP_PER_HOUR" ] || die "budget: $recent experiments started in the last hour (MAX_EXP_PER_HOUR=$MAX_EXP_PER_HOUR)"
    # Records stay out of git: they change on every branch and the corpus
    # (knowledge/records) is their durable copy. Only config and rules are tracked.
    [ -f "$KAIZEN_DIR/.gitignore" ] || printf '*\n!.gitignore\n!config.sh\n!preset.sh\n!RULES.md\n' > "$KAIZEN_DIR/.gitignore"
    n=$(count_matches "$KAIZEN_DIR"/experiments/*/)
    name=$(printf '%03d-%s' "$((n + 1))" "$slug")
    dir="$KAIZEN_DIR/experiments/$name"
    mkdir -p "$dir"
    git -C "$KAIZEN_PROJECT" switch -q -c "exp/$name" "$stable"
    python3 - "$dir/manifest.json" "$name" "$stable" "$(now)" <<'EOF'
import json, sys
path, name, stable, started = sys.argv[1:]
json.dump({
    "schemaVersion": "v1",
    "experimentId": name,
    "patternId": "",
    "hypothesisId": "",
    "hypothesis": "",
    "observations": [{"summary": "", "artifact": ""}],
    "allowedChanges": [{"path": "", "changeKind": "modify", "reason": ""}],
    "changeSummary": "",
    "expectedEffect": "",
    "stableRevision": stable,
    "candidateRevision": None,
    "startedAt": started,
}, open(path, "w"), indent=2, ensure_ascii=False)
EOF
    : > "$dir/timeline.tsv"
    state_set CURRENT_EXPERIMENT "$name"
    echo "$name opened on branch exp/$name from $(short "$stable"); fill $dir/manifest.json, commit the change, then deploy.sh and bench.sh"
    ;;

  current)
    [ -n "$EXP" ] || { echo "no open experiment"; exit 0; }
    echo "$EXP ($EXP_DIR)"
    ls "$EXP_DIR"
    ;;

  record)
    override=""
    if [ "${1:-}" = --override ]; then
      override=${2:?--override needs promote, reject, or inconclusive}
      shift 2
      case "$override" in promote|reject|inconclusive) ;; *) die "override must be promote, reject, or inconclusive" ;; esac
    fi
    reason=${*:-}
    [ -n "$reason" ] || die "give a reason after the decision"
    [ -n "$EXP" ] || die "no open experiment"
    [ -f "$EXP_DIR/decision.json" ] || die "no decision.json; run evaluate.sh first (even to record an override)"
    rule=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["decision"])' "$EXP_DIR/decision.json")
    final=${override:-$rule}
    stable=$(state_get STABLE_REV)
    deployed=$(state_get DEPLOYED_REV)
    head=$(git_head)
    recovery="not-needed"

    if [ "$final" = promote ]; then
      [ "$(state_get REVERT_PENDING)" != 1 ] || die "the candidate failed correctness and cannot be promoted, override or not"
      git_dirty && die "commit the change before promoting"
      [ "$deployed" = "$head" ] || die "deployed ($(short "$deployed")) is not HEAD ($(short "$head")); the promoted revision must be the benchmarked one"
      for host in $APP_HOSTS; do
        [ "$(deployed_marker "$host")" = "$deployed" ] || die "$host marker differs from DEPLOYED_REV; deploy again"
      done
      python3 - "$EXP_DIR" "$deployed" <<'EOF' || die "no passing candidate sample of $(short "$deployed") in $EXP_DIR"
import glob, json, sys
d, rev = sys.argv[1:]
ok = [s for s in (json.load(open(p)) for p in glob.glob(f"{d}/bench-candidate*.json")) if s["pass"] and s["deployedRevision"] == rev]
sys.exit(0 if ok else 1)
EOF
      git -C "$KAIZEN_PROJECT" update-ref "refs/heads/$STABLE_BRANCH" "$head" "$stable" || die "stable branch $STABLE_BRANCH moved away from $(short "$stable"); resolve by hand"
      git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH"
      state_set STABLE_REV "$head"
      state_set REVERT_PENDING 0
      mkdir -p "$KAIZEN_DIR/baseline/$head"
      for f in "$EXP_DIR"/bench-candidate*.json; do
        [ -f "$f" ] && cp "$f" "$KAIZEN_DIR/baseline/$head/$(basename "$f" .json)-reseed.json"
      done
    else
      if [ "$deployed" != "$stable" ] || [ "$(state_get REVERT_PENDING)" = 1 ]; then
        log "candidate is still deployed; recovering stable"
        "$KAIZEN_PLUGIN_ROOT/scripts/recover.sh" >/dev/null && recovery="ok" || recovery="failed"
        [ "$recovery" = ok ] || die "recovery failed; the target is not stable. Fix it before recording"
      fi
      git_dirty && die "commit or discard the working tree changes before closing the experiment"
      git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH"
    fi

    python3 - "$EXP_DIR" "$EXP" "$rule" "$final" "${override:-}" "$reason" "$stable" "$(state_get STABLE_REV)" "$head" "$recovery" "$(now)" <<'EOF'
import glob, json, os, sys
d, exp, rule, final, override, reason, before, after, head, recovery, closed = sys.argv[1:]
manifest = json.load(open(f"{d}/manifest.json"))
manifest["candidateRevision"] = head
json.dump(manifest, open(f"{d}/manifest.json", "w"), indent=2, ensure_ascii=False)
samples = [json.load(open(p)) for p in sorted(glob.glob(f"{d}/bench-*.json"))]
timeline = open(f"{d}/timeline.tsv").read().splitlines() if os.path.exists(f"{d}/timeline.tsv") else []
json.dump({
    "experimentId": exp,
    "manifest": manifest,
    "ruleDecision": json.load(open(f"{d}/decision.json")),
    "finalDecision": final,
    "override": {"decision": override, "reason": reason} if override else None,
    "reason": reason,
    "stableBefore": before,
    "stableAfter": after,
    "candidateRevision": head,
    "samples": samples,
    "recovery": recovery,
    "timeline": timeline,
    "closedAt": closed,
}, open(f"{d}/record.json", "w"), indent=2, ensure_ascii=False)
EOF
    [ -f "$KAIZEN_DIR/log.md" ] || printf '| closed | experiment | candidate | rule | final | scores | reason |\n|---|---|---|---|---|---|---|\n' > "$KAIZEN_DIR/log.md"
    scores=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get("baselineScores")) + " -> " + str(d.get("candidateScores")))' "$EXP_DIR/decision.json")
    printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$(now)" "$EXP" "$(short "$head")" "$rule" "$final" "$scores" "$reason" >> "$KAIZEN_DIR/log.md"
    state_set CURRENT_EXPERIMENT ""
    "$KAIZEN_PLUGIN_ROOT/scripts/knowledge.sh" ingest "$EXP_DIR" || log "knowledge ingest failed; run knowledge.sh ingest $EXP_DIR later"
    echo "$EXP closed: rule=$rule final=$final; stable is $(short "$(state_get STABLE_REV)"), deployed $(short "$(state_get DEPLOYED_REV)")"
    "$KAIZEN_PLUGIN_ROOT/scripts/retro.sh" count
    ;;

  *) die "usage: experiment.sh new <slug> | record [--override <decision>] <reason> | current" ;;
esac
