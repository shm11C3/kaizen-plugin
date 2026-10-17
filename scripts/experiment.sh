#!/usr/bin/env bash
# experiment.sh new <slug> [--github-user <login>]
# experiment.sh record [--override <promote|reject|inconclusive>] <reason...>
# experiment.sh current
#
# One experiment = one hypothesis = one branch [<github-user>/]exp/NNN-<slug> = one directory
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
    shift
    github_user=
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --github-user)
          [ "$#" -ge 2 ] || die "--github-user requires the current operator's GitHub login"
          [ -n "$2" ] || die "--github-user cannot be empty"
          [ -z "$github_user" ] || die "specify --github-user only once"
          github_user=$2
          shift 2
          ;;
        *) die "usage: experiment.sh new <slug> [--github-user <login>]" ;;
      esac
    done
    if [ -n "$github_user" ]; then
      [[ "$github_user" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$ ]] \
        || die "--github-user must be a GitHub login (1-39 alphanumeric/hyphen characters, alphanumeric ends)"
      case "$github_user" in *--*) die "--github-user cannot contain consecutive hyphens" ;; esac
    elif [ "${KAIZEN_TEAM_MODE:-0}" = 1 ]; then
      die "team experiments require --github-user <current operator's GitHub login>"
    fi
    case "$slug" in *[!A-Za-z0-9_-]*) die "slug must be [A-Za-z0-9_-]" ;; esac
    [ -z "$EXP" ] || die "experiment $EXP is still open; record its decision first"
    [ "$(state_get REVERT_PENDING)" != 1 ] || die "a failed candidate is still deployed; recover.sh first"
    no_manual_bench
    verify_bundle
    git_dirty && die "the working tree has uncommitted changes; commit or stash them before a new experiment"
    stable=$(state_get STABLE_REV)
    [ -n "$stable" ] || die "STABLE_REV is not set; run /kaizen:setup"
    recent=$(experiments_started_since $(( $(epoch) - 3600 )))
    [ "$recent" -lt "$MAX_EXP_PER_HOUR" ] || die "budget: $recent experiments started in the last hour (MAX_EXP_PER_HOUR=$MAX_EXP_PER_HOUR)"
    # Records stay out of git: they change on every branch and the corpus
    # (knowledge/records) is their durable copy. Only config and rules are tracked.
    [ -f "$KAIZEN_DIR/.gitignore" ] || printf '*\n!.gitignore\n!config.sh\n!preset.sh\n!RULES.md\n' > "$KAIZEN_DIR/.gitignore"
    # Records (.kaizen/) are committed on the stable branch between
    # experiments, so its tip may sit above STABLE_REV; branch from the tip
    # when the application files are the same, so a promote can fast-forward.
    base=$(git_rev "$STABLE_BRANCH") || die "no branch $STABLE_BRANCH"
    if [ "$base" != "$stable" ]; then
      # shellcheck disable=SC2086
      git -C "$KAIZEN_PROJECT" diff --quiet "$stable" "$base" -- $LOCAL_SYNC_PATHS "$OVERLAY_DIR" ":(glob)$OVERLAY_DIR-*" \
        || die "$STABLE_BRANCH ($(short "$base")) changes deployed files relative to stable $(short "$stable"); re-pin STABLE_REV (setup) or move the branch back"
    fi
    n=$(count_matches "$KAIZEN_DIR"/experiments/*/)
    name=$(printf '%03d-%s' "$((n + 1))" "$slug")
    branch="${github_user:+$github_user/}exp/$name"
    dir="$KAIZEN_DIR/experiments/$name"
    mkdir -p "$dir"
    git -C "$KAIZEN_PROJECT" switch -q -c "$branch" "$base"
    python3 - "$dir/manifest.json" "$name" "$stable" "$(now)" "$KAIZEN_DIR/stable-bundle.json" <<'EOF'
import json, sys
path, name, stable, started, bundle = sys.argv[1:]
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
    "strategy": {
        "mechanism": "", "scoringPath": "", "scoringEvidence": "",
        "expectedImpact": "", "estimatedMinutes": None, "uncertainty": "",
        "disproof": "", "dependsOn": [], "parameters": {}
    },
    "stableRevision": stable,
    "stableBundle": json.load(open(bundle)),
    "candidateRevision": None,
    "review": "auto",
    "humanQuestion": "",
    "changedResources": [],
    "startedAt": started,
}, open(path, "w"), indent=2, ensure_ascii=False)
EOF
    : > "$dir/timeline.tsv"
    state_set CURRENT_EXPERIMENT "$name"
    state_set BENCH_BUDGET_EXPERIMENT "$name"
    echo "$name opened on branch $branch from $(short "$base"); fill $dir/manifest.json, commit the change, then deploy.sh and bench.sh"
    ;;

  current)
    [ -n "$EXP" ] || { echo "no open experiment"; exit 0; }
    echo "$EXP ($EXP_DIR)"
    ls "$EXP_DIR"
    ;;

  record)
    no_manual_bench
    override=""
    human_decision=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --override) override=${2:?--override needs a decision}; shift 2 ;;
        --human-decision) human_decision=${2:?--human-decision needs an actual reference}; shift 2 ;;
        *) break ;;
      esac
    done
    case "$override" in ''|promote|reject|inconclusive) ;; *) die "override must be promote, reject, or inconclusive" ;; esac
    reason=${*:-}
    [ -n "$reason" ] || die "give a reason after the decision"
    [ -n "$EXP" ] || die "no open experiment"
    [ -f "$EXP_DIR/decision.json" ] || die "no decision.json; run evaluate.sh first (even to record an override)"
    "$KAIZEN_PLUGIN_ROOT/scripts/evaluate.sh" >/dev/null
    rule=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["decision"])' "$EXP_DIR/decision.json")
    final=${override:-$rule}
    stable=$(state_get STABLE_REV)
    deployed=$(state_get DEPLOYED_REV)
    head=$(git_head)
    recovery="not-needed"

    if [ "$final" = promote ]; then
      verify_bundle_config
      python3 - "$EXP_DIR/decision.json" <<'EOF' || die "quality or comparable measurement conditions are unresolved; investigate/re-measure, never waive them"
import json,sys
d=json.load(open(sys.argv[1]))
sys.exit(1 if d.get('qualityBlockPromotion',True) else 0)
EOF
      [ "$rule" = promote ] || [ -n "$human_decision" ] || die "ambiguous performance adoption requires --human-decision with a real reference"
      review=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("review","auto"))' "$EXP_DIR/manifest.json")
      [ "$review" != human ] || [ -n "$human_decision" ] || die "this manifest requires a real human decision reference"
      [ "$(state_get REVERT_PENDING)" != 1 ] || die "the candidate failed correctness and cannot be promoted, override or not"
      git_dirty && die "commit the change before promoting"
      [ "$deployed" = "$head" ] || die "deployed ($(short "$deployed")) is not HEAD ($(short "$head")); the promoted revision must be the benchmarked one"
      for host in $APP_HOSTS; do
        [ "$(deployed_marker "$host")" = "$deployed" ] || die "$host marker differs from DEPLOYED_REV; deploy again"
      done
      python3 - "$EXP_DIR" "$deployed" <<'EOF' || die "no passing candidate sample of $(short "$deployed") in $EXP_DIR"
import glob, json, sys
d, rev = sys.argv[1:]
samples=[json.load(open(p)) for p in glob.glob(f"{d}/bench-candidate*.json")]
ok=[s for s in samples if s['pass'] and not s.get('observed') and s['deployedRevision']==rev]
sys.exit(0 if ok and all(s['pass'] for s in samples) else 1)
EOF
      mainrev=$(git_rev "$STABLE_BRANCH")
      git -C "$KAIZEN_PROJECT" merge-base --is-ancestor "$mainrev" "$head" || die "$STABLE_BRANCH ($(short "$mainrev")) is not an ancestor of the candidate; rebase the experiment branch on it and deploy again"
      git -C "$KAIZEN_PROJECT" update-ref "refs/heads/$STABLE_BRANCH" "$head" "$mainrev" || die "stable branch $STABLE_BRANCH moved while recording; resolve by hand"
      git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH"
      state_set STABLE_REV "$head"
      capture_bundle >/dev/null
      state_set REVERT_PENDING 0
      mkdir -p "$KAIZEN_DIR/baseline/$head"
      for f in "$EXP_DIR"/bench-candidate*.json; do
        [ -f "$f" ] || continue
        python3 -c 'import json,sys; sys.exit(1 if json.load(open(sys.argv[1])).get("observed") else 0)' "$f" || continue
        python3 - "$f" "$KAIZEN_DIR/baseline/$head/$(basename "$f" .json)-reseed.json" "$KAIZEN_DIR/stable-bundle.json" <<'EOF'
import json,sys
s=json.load(open(sys.argv[1]));s['measuredAgainstBundle']=s.get('stableBundleId')
s['stableBundleId']=json.load(open(sys.argv[3]))['id']
json.dump(s,open(sys.argv[2],'w'),indent=2)
EOF
      done
    else
      if [ "$deployed" != "$stable" ] || [ "$(state_get REVERT_PENDING)" = 1 ]; then
        log "candidate is still deployed; recovering stable"
        "$KAIZEN_PLUGIN_ROOT/scripts/recover.sh" >/dev/null && recovery="ok" || recovery="failed"
        [ "$recovery" = ok ] || die "recovery failed; the target is not stable. Fix it before recording"
      fi
      verify_bundle
      git_dirty && die "commit or discard the working tree changes before closing the experiment"
      git -C "$KAIZEN_PROJECT" switch -q "$STABLE_BRANCH"
    fi

    python3 - "$EXP_DIR" "$EXP" "$rule" "$final" "${override:-}" "$reason" "$stable" "$(state_get STABLE_REV)" "$head" "$recovery" "$(now)" "$human_decision" <<'EOF'
import glob, json, os, sys
d, exp, rule, final, override, reason, before, after, head, recovery, closed, human = sys.argv[1:]
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
    "humanDecision": human or None,
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
    python3 "$KAIZEN_PLUGIN_ROOT/scripts/strategy.py" --project "$KAIZEN_PROJECT" status
    if [ -f "$KAIZEN_DIR/plan.md" ]; then
      if [ "$final" = promote ]; then hint="observe again and knowledge.sh plan"; else hint="mark the item, adjust the order"; fi
      echo "plan: update .kaizen/plan.md ($final: $hint)"
    fi
    ;;

  *) die "usage: experiment.sh new <slug> | record [--override <decision>] <reason> | current" ;;
esac
