#!/usr/bin/env bash
# End-to-end test of the loop against a fake remote: two app hosts, a fake
# benchmarker, shims for sudo/systemctl/md5sum. Exercises setup, baseline,
# a promoted experiment (with an etc/ overlay change), a correctness-failed
# experiment with recovery, the budget, and the hook guard.
set -euo pipefail

PLUGIN=$(cd "$(dirname "$0")/.." && pwd)
# A session that exported KAIZEN_PROJECT for the real target must not leak it
# into the tests: every script would then act on that project with the fake
# remote (seen 2026-10-17: friction rows and a failed "deploy" in the live repo).
unset KAIZEN_PROJECT KAIZEN_PLUGIN_ROOT KAIZEN_TEAM_MODE
# Git hooks and caller wrappers can export GIT_DIR/GIT_CONFIG, which override
# this suite's temporary cwd. Never configure or commit in the caller's repo.
while IFS= read -r git_variable; do
  case "$git_variable" in GIT_*) unset "$git_variable" ;; esac
done < <(compgen -e)
T=$(mktemp -d "${TMPDIR:-/tmp}/kaizen-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
export KAIZEN_FAKE_REMOTE="$T/remote"
mkdir -p "$KAIZEN_FAKE_REMOTE" "$T/bin"

# Shims used by commands the scripts run "on the host".
cat > "$T/bin/sudo" <<'EOF'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case "$1" in -u|-i) [ "$1" = -u ] && shift; shift ;; -*) shift ;; *) break ;; esac; done
exec "$@"
EOF
cat > "$T/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $* ($FAKE_HOST)" >> "$KAIZEN_FAKE_REMOTE/systemctl.log"
EOF
cat > "$T/bin/md5sum" <<'EOF'
#!/usr/bin/env bash
python3 -c 'import hashlib,sys
for p in sys.argv[1:]:
    print(hashlib.md5(open(p,"rb").read()).hexdigest()+"  "+p)' "$@"
EOF
chmod +x "$T/bin/"*
export PATH="$T/bin:$PATH"
cp -R "$PLUGIN/knowledge" "$T/knowledge"
export KAIZEN_KNOWLEDGE_DIR="$T/knowledge"

P="$T/project"
mkdir -p "$P/go" "$P/sql" "$P/etc/mysql" "$P/.kaizen"
cd "$P"
git init -q -b main
git config user.email test@example.com
git config commit.gpgsign false   # the operator's signing helper must not be needed to run the suite
git config user.name test
echo 1000 > go/score
echo 'CREATE TABLE t (id INT PRIMARY KEY);' > sql/1-schema.sql
echo 'innodb_flush_log_at_trx_commit=1' > etc/mysql/my.cnf
git add -A && git commit -qm "stable"
cat > .kaizen/config.sh <<EOF
. "\$KAIZEN_PLUGIN_ROOT/presets/isucon14.sh"
APP_HOST=isu1
APP_HOSTS="isu1 isu2"
BENCH_HOST=bench
APP_PRIVATE_IP=10.0.0.1
BENCH_PRIVATE_IP=10.0.0.2
REMOTE_APP_DIR=webapp
RSYNC_PATH=""
SYNC_EXCLUDES=""
BUILD_CMD='test -f webapp/go/score'
RESTART_CMD='sudo systemctl restart app.service'
HEALTH_CMD='true'
bench_command() { echo "bash $PLUGIN/tests/fake-bench.sh"; }
MAX_BENCH_PER_EXP=3
RECOVERY_BENCH_RESERVE=0  # dedicated budget tests cover the default reserved recovery slot
RESOURCE_FINGERPRINT_CMD='test ! -f fail-probe && cat database.state'
RECOVERY_CMD='test ! -f fail-recovery && cp webapp/sql/1-schema.sql database.state'
BENCH_PRECHECK_CMD='test ! -f busy.marker'
PROBLEM=test
RETRO_BLOCK_AFTER=1000
EVALUATION_RULE=v2
REQUEST_COUNT_CMD='wc -l < access.log 2>/dev/null || echo 0'
EOF

S="$PLUGIN/scripts"
fail() { echo "FAIL: $*" >&2; exit 1; }
expect_fail() { if "$@" >/dev/null 2>&1; then fail "expected failure: $*"; fi; }
state() { sed -n "s/^$1=//p" .kaizen/state.env | tail -1; }

echo "== setup: pin stable, deploy, recovery drill"
printf 'STABLE_REV=%s\n' "$(git rev-parse main)" > .kaizen/state.env
expect_fail "$S/bench.sh" baseline                    # nothing deployed yet
"$S/deploy.sh" main >/dev/null
for host in isu1 isu2; do cp "$KAIZEN_FAKE_REMOTE/$host/webapp/sql/1-schema.sql" "$KAIZEN_FAKE_REMOTE/$host/database.state"; done
msg=$("$S/experiment.sh" new too-early 2>&1 || true)
printf '%s' "$msg" | grep -q "stable bundle missing" || fail "a missing bundle is named as such, not as a changed configuration: $msg"
"$S/stable.sh" capture >/dev/null
[ "$(state DEPLOYED_REV)" = "$(git rev-parse main)" ] || fail "DEPLOYED_REV after deploy"
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu2/webapp/.deployed-revision")" = "$(git rev-parse main)" ] || fail "marker on isu2"
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu1/etc/mysql/my.cnf")" = "innodb_flush_log_at_trx_commit=1" ] || fail "overlay synced"
"$S/recover.sh" >/dev/null
"$S/verify.sh" main >/dev/null
python3 -c 'import json,sys; b=json.load(open(sys.argv[1])); assert b.get("pluginRevision") and b.get("capturedAt"), b' .kaizen/stable-bundle.json || fail "bundle records the plugin revision as provenance"
# The bundle binds measurement conditions, not the plugin or non-measurement settings.
echo "TIME_BUDGET_MIN=480" >> .kaizen/config.sh
(. "$S/lib.sh"; load_config; verify_bundle_config) || fail "a non-measurement setting must not retire the bundle"
echo "BUILD_CMD='test -f webapp/go/score || true'" >> .kaizen/config.sh
(. "$S/lib.sh"; load_config; verify_bundle_config) 2>/dev/null && fail "a changed build command must retire the bundle"
sed -i '' '$d' .kaizen/config.sh
(. "$S/lib.sh"; load_config; verify_bundle_config) || fail "restored build command matches the bundle again"
cp .kaizen/stable-bundle.json "$T/original-bundle.json"
touch "$KAIZEN_FAKE_REMOTE/isu1/fail-probe"
expect_fail "$S/stable.sh" capture
cmp .kaizen/stable-bundle.json "$T/original-bundle.json" || fail "failed probe must not bless empty resource fingerprints"
rm "$KAIZEN_FAKE_REMOTE/isu1/fail-probe"

echo "== baseline"
expect_fail "$S/bench.sh" candidate                   # no experiment open
"$S/bench.sh" baseline >/dev/null
"$S/bench.sh" baseline-2 >/dev/null
[ "$(ls .kaizen/baseline/"$(git rev-parse main)"/*.json | wc -l | tr -d ' ')" = 2 ] || fail "baseline samples filed"

echo "== precheck: a busy host refuses a sample; forget-baseline retires contaminated samples"
touch "$KAIZEN_FAKE_REMOTE/isu2/busy.marker"
expect_fail "$S/bench.sh" baseline-pc1
[ ! -e .kaizen/bench-baseline-pc1.json ] || fail "no sample recorded when the precheck fails"
rm "$KAIZEN_FAKE_REMOTE/isu2/busy.marker"
"$S/bench.sh" baseline-pc1 >/dev/null
[ "$(ls .kaizen/baseline/"$(git rev-parse main)"/*.json | wc -l | tr -d ' ')" = 3 ] || fail "third baseline sample filed"
"$S/stable.sh" forget-baseline "test: upgrade ran during the samples" >/dev/null
[ ! -d .kaizen/baseline/"$(git rev-parse main)" ] || fail "baseline directory retired"
[ "$(ls .kaizen/baseline/"$(git rev-parse main)".retired-*/*.json | wc -l | tr -d ' ')" = 3 ] || fail "retired samples kept as evidence"
grep -q "upgrade ran" .kaizen/baseline/"$(git rev-parse main)".retired-*/REASON.txt || fail "reason kept"
expect_fail "$S/stable.sh" forget-baseline "nothing left"
"$S/bench.sh" baseline-pc2 >/dev/null
"$S/bench.sh" baseline-pc3 >/dev/null

echo "== resource recovery: a code SHA alone does not restore a database"
echo extra-index > "$KAIZEN_FAKE_REMOTE/isu1/database.state"
"$S/deploy.sh" main >/dev/null
expect_fail "$S/bench.sh" baseline-stale-db
touch "$KAIZEN_FAKE_REMOTE/isu1/fail-recovery"
expect_fail "$S/recover.sh"
[ "$(state REVERT_PENDING)" = 1 ] || fail "failed resource restore keeps recovery pending"
rm "$KAIZEN_FAKE_REMOTE/isu1/fail-recovery"
"$S/recover.sh" >/dev/null
cmp "$KAIZEN_FAKE_REMOTE/isu1/database.state" "$KAIZEN_FAKE_REMOTE/isu1/webapp/sql/1-schema.sql" || fail "original schema restored"

echo "== repin: records committed on main move the branch, not the servers"
echo "- no rule" > .kaizen/RULES.md && git add .kaizen/RULES.md && git commit -qm "records"
"$S/stable.sh" repin >/dev/null
[ "$(state STABLE_REV)" = "$(git rev-parse main)" ] || fail "STABLE_REV follows main after repin"
[ "$(state DEPLOYED_REV)" = "$(git rev-parse main)" ] || fail "DEPLOYED_REV re-keyed"
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu1/webapp/.deployed-revision")" = "$(git rev-parse main)" ] || fail "marker re-keyed"
[ "$(ls .kaizen/baseline/"$(git rev-parse main)"/*.json | wc -l | tr -d ' ')" = 2 ] || fail "baseline samples re-keyed"
grep -q repinnedFrom .kaizen/baseline/"$(git rev-parse main)"/*.json || fail "re-keyed sample notes its origin"
"$S/verify.sh" main >/dev/null
git switch -q -c tmp-code && echo 3000 > go/score && git commit -qam "code change"
expect_fail "$S/stable.sh" repin tmp-code              # deployable tree differs: a candidate, not a repin
git switch -q main && git branch -q -D tmp-code

echo "a record changed" >> .kaizen/RULES.md             # tracked records never count as a dirty tree

echo "== experiment 1: promoted, with overlay change"
expect_fail "$S/deploy.sh" HEAD~0 --dirty             # bad usage
expect_fail env KAIZEN_TEAM_MODE=1 "$S/experiment.sh" new flush-log
expect_fail env KAIZEN_TEAM_MODE=1 "$S/experiment.sh" new flush-log --github-user ../outside
expect_fail "$S/experiment.sh" new flush-log --github-user
[ ! -d .kaizen/experiments/001-flush-log ] || fail "invalid identity created an experiment"
env KAIZEN_TEAM_MODE=1 "$S/experiment.sh" new flush-log --github-user Member-01 >/dev/null
git restore .kaizen/RULES.md
[ "$(git branch --show-current)" = "Member-01/exp/001-flush-log" ] || fail "GitHub user experiment branch"
echo 2000 > go/score
echo 'innodb_flush_log_at_trx_commit=2' > etc/mysql/my.cnf
git commit -qam "candidate: flush log every second"
expect_fail "$S/deploy.sh" HEAD                        # manifest not filled
git add -f .kaizen/experiments/001-flush-log/manifest.json && git commit -qm "oops: records in the candidate"
expect_fail "$S/deploy.sh" HEAD                        # candidate carries .kaizen records
git rm -q --cached .kaizen/experiments/001-flush-log/manifest.json && git commit -qm "records untracked"
python3 - <<'EOF'
import json
p = ".kaizen/experiments/001-flush-log/manifest.json"
m = json.load(open(p))
m.update(patternId="fsync-on-commit", hypothesisId="flush-log", hypothesis="COMMIT waits on fsync", expectedEffect="score up",
         observations=[{"summary": "COMMIT 60s total", "artifact": ".kaizen/observe-baseline.txt"}],
         allowedChanges=[{"path": "etc/mysql/my.cnf", "changeKind": "modify", "reason": "flush setting"}])
json.dump(m, open(p, "w"), indent=2)
EOF
: > "$KAIZEN_FAKE_REMOTE/systemctl.log"
"$S/deploy.sh" HEAD >/dev/null
grep -q "restart mysql.service (isu1)" "$KAIZEN_FAKE_REMOTE/systemctl.log" || fail "mysql restarted on overlay change"
grep -q "restart mysql.service (isu2)" "$KAIZEN_FAKE_REMOTE/systemctl.log" || fail "mysql restarted on isu2"
expect_fail "$S/bench.sh" baseline                     # candidate deployed, not stable
"$S/bench.sh" candidate >/dev/null
python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); assert s.get("pluginRevision"), s; assert isinstance(s.get("requests"), int) and s["requests"] > 100, s.get("requests")' .kaizen/experiments/001-flush-log/bench-candidate.json || fail "sample records the plugin revision and the access-log request delta"
"$S/bench.sh" candidate-2 >/dev/null
"$S/evaluate.sh" >/dev/null
[ "$(python3 -c 'import json; print(json.load(open(".kaizen/experiments/001-flush-log/decision.json"))["decision"])')" = promote ] || fail "rule should promote"
"$S/experiment.sh" record "indexes and flush setting, +100%" >/dev/null
cand=$(git rev-parse Member-01/exp/001-flush-log)
[ "$(state STABLE_REV)" = "$cand" ] || fail "STABLE_REV promoted"
[ "$(git rev-parse main)" = "$cand" ] || fail "main fast-forwarded"
[ "$(git branch --show-current)" = main ] || fail "back on main"
[ "$(state CURRENT_EXPERIMENT)" = "" ] || fail "experiment closed"
ls .kaizen/baseline/"$cand"/*.json >/dev/null || fail "baseline reseeded"
[ -f .kaizen/experiments/001-flush-log/record.json ] || fail "record.json"
grep -q "001-flush-log" .kaizen/log.md || fail "log.md row"
grep -q "| test | 001-flush-log |" "$T/knowledge/patterns/fsync-on-commit.md" || fail "ingest appended a measured row"
[ -f "$T/knowledge/records/test/001-flush-log.json" ] || fail "record filed under records/<problem>"
grep -q "001-flush-log" "$T/knowledge/problems/test.md" || fail "problem log row"
"$S/knowledge.sh" ingest .kaizen/experiments/001-flush-log | grep -q "already ingested" || fail "ingest is idempotent"

# Records are committed on main between experiments; the next promote must still fast-forward.
printf '.kaizen/bench.lock\n.kaizen/state.env\n.kaizen/friction.jsonl\n' > .gitignore
git add .gitignore .kaizen && git commit -qm "records: experiment 1"
[ "$(git rev-parse main)" != "$(state STABLE_REV)" ] || fail "test setup: main should be ahead of stable"

echo "== experiment 2: correctness failure, recovery, reject"
"$S/experiment.sh" new break-it >/dev/null
echo fail > go/score
git commit -qam "candidate: broken"
python3 - <<'EOF'
import json
p = ".kaizen/experiments/002-break-it/manifest.json"
m = json.load(open(p))
m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}])
json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
expect_fail "$S/bench.sh" candidate                    # pass=false -> exit 1
[ "$(state REVERT_PENDING)" = 1 ] || fail "REVERT_PENDING set"
expect_fail "$S/deploy.sh" HEAD                        # blocked until recover
expect_fail "$S/experiment.sh" new another             # blocked until recover
"$S/recover.sh" >/dev/null
[ "$(state REVERT_PENDING)" = 0 ] || fail "REVERT_PENDING cleared"
[ "$(state DEPLOYED_REV)" = "$cand" ] || fail "stable redeployed"
"$S/evaluate.sh" >/dev/null
[ "$(python3 -c 'import json; print(json.load(open(".kaizen/experiments/002-break-it/decision.json"))["decision"])')" = reject ] || fail "rule should reject"
expect_fail "$S/experiment.sh" record --override promote "no"   # cannot promote a failed candidate
"$S/experiment.sh" record "broke correctness" >/dev/null
[ "$(git branch --show-current)" = main ] || fail "back on main after reject"

echo "== experiment 3: inconclusive by rule, override, budget"
"$S/experiment.sh" new tiny >/dev/null
echo 2010 > go/score
git commit -qam "candidate: tiny"
python3 - <<'EOF'
import json
p = ".kaizen/experiments/003-tiny/manifest.json"
m = json.load(open(p)); m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}]); json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
"$S/bench.sh" candidate >/dev/null
"$S/bench.sh" candidate-2 >/dev/null
"$S/bench.sh" candidate-3 >/dev/null
expect_fail "$S/bench.sh" candidate-4                  # MAX_BENCH_PER_EXP=3
"$S/evaluate.sh" >/dev/null
[ "$(python3 -c 'import json; print(json.load(open(".kaizen/experiments/003-tiny/decision.json"))["decision"])')" = inconclusive ] || fail "rule should be inconclusive"
"$S/experiment.sh" record --override reject "too small to keep" >/dev/null
python3 -c 'import json; r=json.load(open(".kaizen/experiments/003-tiny/record.json")); assert r["finalDecision"]=="reject" and r["override"]["decision"]=="reject" and r["ruleDecision"]["decision"]=="inconclusive"' || fail "override recorded"
[ "$(state DEPLOYED_REV)" = "$cand" ] || fail "stable back after override reject"
expect_fail "$S/bench.sh" baseline-after-close         # closed experiments still own their recovery budget

# Explicit hourly experiment caps still apply; zero removes only that cap.
echo 'MAX_EXP_PER_HOUR=1' >> .kaizen/config.sh
expect_fail "$S/experiment.sh" new explicit-hour-limit
echo 'MAX_EXP_PER_HOUR=0' >> .kaizen/config.sh
"$S/status.sh" > "$T/count-limits.txt"
grep -q 'total unlimited; hourly unlimited' "$T/count-limits.txt" || fail 'zero count caps are displayed as unlimited'
grep -q '/unlimited experiments this hour' "$T/count-limits.txt" || fail 'zero experiment cap is displayed as unlimited'

echo "== manual bench mode"
cat >> .kaizen/config.sh <<'EOF'
BENCH_MODE=manual
EOF
"$S/stable.sh" capture >/dev/null                       # mode changed: retire incomparable baselines
expect_fail "$S/bench.sh" baseline-3                   # needs --result
expect_fail "$S/bench.sh" baseline-3 --result 'pass=true score=2100 errors=none'
"$S/bench.sh" baseline-3 --reserve >/dev/null
expect_fail "$S/deploy.sh" main                        # portal operation remains active between CLI calls
"$S/bench.sh" baseline-3 --result 'pass=true score=2100 errors=none' --seconds 65 >/dev/null
python3 -c 'import json,glob; s=[json.load(open(p)) for p in glob.glob(".kaizen/baseline/*/bench-*baseline-3.json")]; assert s and s[0]["score"]==2100 and s[0]["mode"]=="manual"' || fail "manual sample"
"$S/bench.sh" baseline --reserve >/dev/null
"$S/bench.sh" baseline --result 'pass=true score=2050 errors=none' >/dev/null
[ "$(ls .kaizen/baseline/"$(state STABLE_REV)"/bench-*-baseline.json | wc -l | tr -d ' ')" = 1 ] || fail "stable baseline sample filed under the new stable"
[ ! -e .kaizen/bench-baseline.json ] || fail "no top-level sample file outside an experiment"

echo "== hook guard"
G="$PLUGIN/hooks/guard.py"
hook() { python3 "$G" <<<"$1"; }
denied() { hook "$1" | grep -q '"deny"' || fail "should deny: $1"; }
allowed() { [ -z "$(hook "$1")" ] || fail "should allow: $1"; }
cwd_json() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","cwd":sys.argv[1],"tool_name":sys.argv[2],"tool_input":json.loads(sys.argv[3])}))' "$P" "$1" "$2"; }
denied "$(cwd_json Bash '{"command":"ssh isubench sudo -i -u isucon ./bench run --target x --payment-url y"}')"
denied "$(cwd_json Bash '{"command":"rsync -a go/ isu1:/home/isucon/webapp/go/"}')"
denied "$(cwd_json Bash '{"command":"ssh isu1 sudo systemctl restart isuride-go.service"}')"
denied "$(cwd_json Bash '{"command":"git reset --hard HEAD~1"}')"
denied "$(cwd_json Bash '{"command":"echo {} > .kaizen/experiments/001-flush-log/decision.json"}')"
denied "$(cwd_json Write '{"file_path":"'"$P"'/.kaizen/experiments/001-flush-log/record.json","content":"x"}')"
allowed "$(cwd_json Bash '{"command":"cat .kaizen/experiments/001-flush-log/decision.json"}')"
allowed "$(cwd_json Bash '{"command":"ssh isu1 sudo mysql -e \"show processlist\""}')"
allowed "$(cwd_json Bash '{"command":"'"$S"'/bench.sh candidate"}')"
allowed "$(cwd_json Write '{"file_path":"'"$P"'/.kaizen/experiments/001-flush-log/manifest.json","content":"x"}')"
mkdir .kaizen/bench.lock
denied "$(cwd_json Bash '{"command":"'"$S"'/deploy.sh HEAD"}')"
rmdir .kaizen/bench.lock
# Stop: candidate deployed without decision -> block; clean -> silent
"$S/experiment.sh" new stop-check >/dev/null
echo 2500 > go/score; git commit -qam "candidate"
python3 - <<'EOF'
import json
p = ".kaizen/experiments/004-stop-check/manifest.json"
m = json.load(open(p)); m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}]); json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")" | grep -q '"block"' || fail "Stop should block with candidate deployed"
[ -z "$(hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":True}))' "$P")")" ] || fail "Stop must not loop"
"$S/bench.sh" candidate --reserve >/dev/null
"$S/bench.sh" candidate --result 'pass=true score=2600 errors=none' >/dev/null
"$S/bench.sh" candidate-2 --reserve >/dev/null
"$S/bench.sh" candidate-2 --result 'pass=true score=2601 errors=none' >/dev/null
"$S/evaluate.sh" >/dev/null
"$S/experiment.sh" record "stop check" >/dev/null
[ "$(python3 -c 'import json; print(json.load(open(".kaizen/experiments/004-stop-check/record.json"))["finalDecision"])')" = promote ] || fail "exp 4 should promote"
[ "$(git rev-parse main)" = "$(state STABLE_REV)" ] || fail "promote fast-forwarded main past the records commit"
git merge-base --is-ancestor "$(git rev-parse Member-01/exp/001-flush-log)" main || fail "promoted main keeps the earlier history"
git log --format=%s main | grep "records: experiment 1" >/dev/null || fail "promoted main keeps the records commit"   # no -q: pipefail + SIGPIPE
[ -z "$(hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")")" ] || fail "Stop should be silent when clean"
hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"SessionStart","cwd":sys.argv[1]}))' "$P")" | grep -q additionalContext || fail "SessionStart context"

echo "== knowledge: match, stats, stub"
out=$("$S/knowledge.sh" match "$PLUGIN/tests/fixtures/observe-isucon14-initial.txt")
for pid in missing-secondary-index fsync-on-commit random-order-matching hot-polling-endpoint auth-lookup-per-request; do
  printf '%s' "$out" | grep -q "\] $pid " || fail "matcher should report $pid"
done
printf '%s' "$out" | grep -q "1 measured, 1 promoted" || fail "measured summary from pattern file"
"$S/knowledge.sh" stats | grep -q "^fsync-on-commit" || fail "stats lists patterns"
[ -f "$T/knowledge/patterns/unclassified.md" ] || fail "stub pattern for an experiment without patternId"
python3 "$PLUGIN/knowledge/match.py" "$PLUGIN/tests/fixtures/observe-isucon14-initial.txt" --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[0]["stage"]=="early", r[0]'
out=$("$S/knowledge.sh" match "$PLUGIN/tests/fixtures/observe-isucon12-initial.txt")
printf '%s' "$out" | grep -q "prepared statements" || fail "matcher says when the MySQL digest is blind to the app"
printf '%s' "$out" | grep -q "endpoint latency rows" || fail "matcher parses the extra section's latency table"
printf '%s' "$out" | grep -q "\] id-generation-table " || fail "matcher names the generator table from the index list"
printf '%s' "$out" | grep -q "\] single-row-insert-loop " || fail "matcher names a slow POST endpoint as a per-row write loop"
printf '%s' "$out" | grep -q "GET /api/player/competition/:id/ranking 200: 472 calls" || fail "endpoint rows reported"

echo "== retro: friction capture, resolve, stop block"
[ -f .kaizen/friction.jsonl ] || fail "friction.jsonl written by refused calls"
"$S/retro.sh" list | grep -q "bench.sh die" || fail "retro list groups die entries"
"$S/retro.sh" note "skill step 2 unclear" >/dev/null
"$S/retro.sh" list | grep -q "skill step 2 unclear" || fail "retro note"
n=$("$S/retro.sh" count | sed -n 's/friction: \([0-9]*\) .*/\1/p'); [ "$n" -gt 0 ] || fail "retro count"
echo "RETRO_BLOCK_AFTER=1" >> .kaizen/config.sh
hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")" | grep -q "friction" || fail "Stop blocks on unresolved friction"
ids=$(python3 -c 'import json,sys; print(" ".join(str(i) for i,l in enumerate(open(sys.argv[1]),1) if l.strip() and not json.loads(l).get("resolved")))' .kaizen/friction.jsonl)
export KAIZEN_RETRO_LOG="$T/retro/log.md"; mkdir -p "$T/retro"
# shellcheck disable=SC2086
"$S/retro.sh" resolve $ids --fix "test: expected guards" >/dev/null
[ "$("$S/retro.sh" count | sed -n 's/friction: \([0-9]*\) .*/\1/p')" = 0 ] || fail "all resolved"
[ -z "$(hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")")" ] || fail "Stop silent after resolve"
grep -q "test: expected guards" "$KAIZEN_RETRO_LOG" || fail "retro log row"

echo "== plan: ranked candidates, stop hook asks for an update"
"$S/knowledge.sh" plan "$PLUGIN/tests/fixtures/observe-isucon14-initial.txt" | grep -q "candidates ranked" || fail "plan written"
grep -q "| 1 | " .kaizen/plan.md || fail "plan has a ranked row"
grep -q "elapsed" .kaizen/plan.md || fail "plan shows the time budget"
python3 - <<'PYTEST'
from pathlib import Path
p=Path('.kaizen/plan.md'); text=p.read_text()
text=text.replace(' | ? |', ' | direct: fixture manual scoring |', 1)
text = text.replace('## Notes', '| 0 | new-structural-option | unknown | | independent observation | none | indirect CPU | unknown | 12 | high | none | no queue reduction | fixture strategy choice | 12 min |\n\n## Notes')
p.write_text(text)
PYTEST
echo "- keep me" >> .kaizen/plan.md
"$S/knowledge.sh" plan "$PLUGIN/tests/fixtures/observe-isucon14-initial.txt" >/dev/null
grep -q "keep me" .kaizen/plan.md || fail "notes preserved on regenerate"
grep -q "direct: fixture manual scoring" .kaizen/plan.md || fail "scoring choices preserved on regenerate"
grep -q "new-structural-option" .kaizen/plan.md || fail "unmatched structural option preserved"
grep -q "fixture strategy choice" .kaizen/plan.md || fail "structural reasoning preserved"
"$S/strategy.sh" review > "$T/review.md"
grep -q "AI investigation" "$T/review.md" || fail "strategy entry point"
"$S/status.sh" >/dev/null
touch -t 200001010000 .kaizen/plan.md
hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")" | grep -q "plan.md" || fail "Stop asks for a plan update after a record"
touch .kaizen/plan.md
[ -z "$(hook "$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","cwd":sys.argv[1],"stop_hook_active":False}))' "$P")")" ] || fail "Stop silent once the plan is newer"
echo "== observe: reset clears the extra source, dump appends the extra command"
cat >> .kaizen/config.sh <<'EOF2'
MYSQL_CMD=true
DB_NAME=test
ACCESS_LOG=access.log
OBSERVE_RESET_CMD='echo cleared > reset.marker'
OBSERVE_EXTRA_CMD='echo extra-evidence-line'
OBSERVE_START_CMD='test ! -f observation-start-fail'
OBSERVE_STOP_CMD='test ! -f observation-stop-fail'
OBSERVE_TOOLS=otel,pprof
MAX_BENCH_PER_EXP=4
PATH_ID_REGEX='/[0-9a-f]{8,}'
EOF2
printf '127.0.0.1 - - [x +0000] "GET /api/x/0123456789abcdef0123456789 HTTP/2.0" 200 1 "-" "b"\n' > "$KAIZEN_FAKE_REMOTE/isu1/access.log"
"$S/observe.sh" reset >/dev/null
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu1/reset.marker")" = cleared ] || fail "OBSERVE_RESET_CMD ran on the nginx host"
[ ! -s "$KAIZEN_FAKE_REMOTE/isu1/access.log" ] || fail "access log truncated on reset"
printf '127.0.0.1 - - [x +0000] "GET /api/x/0123456789abcdef0123456789 HTTP/2.0" 200 1 "-" "b"\n' > "$KAIZEN_FAKE_REMOTE/isu1/access.log"
dump=$("$S/observe.sh" dump test)
grep -q "extra-evidence-line" "$dump" || fail "OBSERVE_EXTRA_CMD output appended to the dump"
grep -q '/api/x/:id' "$dump" || fail "ids normalized in the request section"
echo "== observed samples are evidence, not measurements"
"$S/stable.sh" capture >/dev/null
for label in baseline-observe-1 baseline-observe-2; do
  "$S/bench.sh" "$label" --reserve >/dev/null
  "$S/bench.sh" "$label" --result 'pass=true score=2600 errors=none' >/dev/null
done
"$S/experiment.sh" new observed >/dev/null
echo 3000 > go/score; git commit -qam "candidate: observed"
python3 - <<'EOF'
import json
p = ".kaizen/experiments/005-observed/manifest.json"
m = json.load(open(p)); m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}]); json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
printf 'OBSERVE_SLOWLOG=1\n' >> .kaizen/state.env          # what observe.sh reset does in slowlog mode
"$S/observe.sh" status | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["slowlogActive"] and r["observed"] and r["session"] is None'
"$S/bench.sh" candidate --reserve >/dev/null
"$S/bench.sh" candidate --result 'pass=true score=9000 errors=none' | grep -q "observed; not used by the rule" || fail "observed sample announced"
printf 'OBSERVE_SLOWLOG=0\n' >> .kaizen/state.env
"$S/evaluate.sh" | grep -q '"inconclusive"' || fail "an observed-only candidate cannot decide"
"$S/evaluate.sh" | grep -q "1 observation samples were left out" || fail "reason names the ignored sample"
# Partial collector start/stop remains excluded from decisions.
touch "$KAIZEN_FAKE_REMOTE/isu1/observation-start-fail" "$KAIZEN_FAKE_REMOTE/isu1/observation-stop-fail"
"$S/observe.sh" start profile >"$T/start.log" 2>&1 && fail "failed start must fail"
test -f .kaizen/observation-active.json || fail "failed start marker retained"
"$S/observe.sh" status | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["session"]["tools"]==["otel","pprof"] and r["observed"]'
"$S/observe.sh" stop >"$T/stop.log" 2>&1 && fail "failed stop must fail"
test -f .kaizen/observation-active.json || fail "failed stop marker retained"
"$S/bench.sh" candidate-profile --reserve >/dev/null
"$S/bench.sh" candidate-profile --result 'pass=true score=9900 errors=none' >/dev/null
python3 - <<'PY'
import json
r=json.load(open('.kaizen/experiments/005-observed/bench-candidate-profile.json'))
assert r['observed'] and r['observationSession']['tools']==['otel','pprof'],r
PY
"$S/evaluate.sh" | grep -q '"inconclusive"' || fail "profile score cannot decide"
rm "$KAIZEN_FAKE_REMOTE/isu1/observation-start-fail" "$KAIZEN_FAKE_REMOTE/isu1/observation-stop-fail"
"$S/observe.sh" stop >/dev/null
test ! -f .kaizen/observation-active.json || fail "successful stop archives marker"
"$S/observe.sh" start successful >/dev/null
"$S/observe.sh" stop >/dev/null
"$S/bench.sh" candidate-2 --reserve >/dev/null
"$S/bench.sh" candidate-2 --result 'pass=true score=2700 errors=none' >/dev/null
"$S/evaluate.sh" | grep -q '"inconclusive"' || fail "one measured candidate is insufficient"
"$S/bench.sh" candidate-3 --reserve >/dev/null
"$S/bench.sh" candidate-3 --result 'pass=true score=2701 errors=none' >/dev/null
"$S/evaluate.sh" | grep -q '"promote"' || fail "measured sample decides"
"$S/experiment.sh" record "observed check" >/dev/null
ls .kaizen/baseline/"$(state STABLE_REV)"/ | grep -q "candidate-2-reseed" || fail "measured candidate reseeded"
ls .kaizen/baseline/"$(state STABLE_REV)"/ | grep -q "bench-candidate-reseed" && fail "observed candidate must not reseed the baseline"

echo "== quality: score gain and a human reference cannot waive unexplained errors"
"$S/experiment.sh" new quality >/dev/null
echo 6000 > go/score; git commit -qam 'candidate: more throughput with unexplained errors'
python3 - <<'EOF'
import json
p='.kaizen/experiments/006-quality/manifest.json'
m=json.load(open(p));m.update(hypothesis='x',expectedEffect='y',observations=[{'artifact':'a'}]);json.dump(m,open(p,'w'))
EOF
"$S/deploy.sh" HEAD >/dev/null
for label in candidate candidate-2; do
  "$S/bench.sh" "$label" --reserve >/dev/null
  "$S/bench.sh" "$label" --result 'pass=true score=6000 errors=map[25:12]' >/dev/null
done
"$S/evaluate.sh" | grep -q 'investigate' || fail 'unexplained errors need investigation'
expect_fail "$S/experiment.sh" record --override promote --human-decision 'fixture: approval cannot waive quality' 'no'
"$S/experiment.sh" record 'needs AI investigation, not a human waiver' >/dev/null
before=$(wc -l < .kaizen/bench-attempts.jsonl)
"$S/bench.sh" baseline-abandoned --reserve >/dev/null
expect_fail "$S/stable.sh" capture
"$S/bench.sh" baseline-abandoned --abandon 'fixture: portal run confirmed ended without a result' >/dev/null
after=$(wc -l < .kaizen/bench-attempts.jsonl)
[ "$after" -eq "$((before + 1))" ] || fail 'abandoned portal attempt stays counted'

echo "== rule v3 (opt-in): one clear sample promotes, one below every baseline rejects, surges and new kinds block"
cat >> .kaizen/config.sh <<'EOF'
EVALUATION_RULE=v3
MAX_EXP_PER_HOUR=50
EOF
v3_stable=$(state STABLE_REV)
[ "$(state DEPLOYED_REV)" = "$v3_stable" ] || "$S/recover.sh" >/dev/null
"$S/bench.sh" baseline --reserve >/dev/null && "$S/bench.sh" baseline --result 'pass=true score=2000 errors=map[25:3]' >/dev/null
"$S/bench.sh" baseline-2 --reserve >/dev/null && "$S/bench.sh" baseline-2 --result 'pass=true score=2200 errors=map[25:5]' >/dev/null
"$S/experiment.sh" new v3-big >/dev/null
echo 9000 > go/score; git commit -qam "candidate: big"
d=$(ls -d .kaizen/experiments/*-v3-big)
python3 - "$d/manifest.json" <<'EOF'
import json, sys
p = sys.argv[1]; m = json.load(open(p)); m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}]); json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
"$S/bench.sh" candidate --reserve >/dev/null && "$S/bench.sh" candidate --result 'pass=true score=9000 errors=map[25:4]' >/dev/null
"$S/evaluate.sh" >/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ruleVersion"]=="plugin-rule-v3" and d["decision"]=="promote" and d["singleSample"] is True, d' "$d/decision.json" || fail "v3 promotes on one clear sample with known error kinds at similar counts"
"$S/experiment.sh" record "v3 one-sample promote" >/dev/null
[ "$(state STABLE_REV)" = "$(git rev-parse HEAD)" ] || fail "v3 promote moved stable"
"$S/bench.sh" baseline --reserve >/dev/null && "$S/bench.sh" baseline --result 'pass=true score=9100 errors=map[25:4]' >/dev/null
"$S/experiment.sh" new v3-worse >/dev/null
echo 100 > go/score; git commit -qam "candidate: worse"
d=$(ls -d .kaizen/experiments/*-v3-worse)
python3 - "$d/manifest.json" <<'EOF'
import json, sys
p = sys.argv[1]; m = json.load(open(p)); m.update(hypothesis="x", expectedEffect="y", observations=[{"summary": "s", "artifact": "a"}]); json.dump(m, open(p, "w"))
EOF
"$S/deploy.sh" HEAD >/dev/null
"$S/bench.sh" candidate --reserve >/dev/null && "$S/bench.sh" candidate --result 'pass=true score=5000 errors=map[25:4]' >/dev/null
"$S/evaluate.sh" >/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["decision"]=="reject" and d["nextAction"]=="reject", d' "$d/decision.json" || fail "v3 rejects a single sample below every baseline sample"
"$S/bench.sh" candidate-2 --reserve >/dev/null && "$S/bench.sh" candidate-2 --result 'pass=true score=20000 errors=map[25:40]' >/dev/null   # median now above baseline: only the error surge blocks
"$S/evaluate.sh" >/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["decision"]=="inconclusive" and d["nextAction"]=="investigate" and "sharply" in d["reason"], d' "$d/decision.json" || fail "v3 blocks a sharp rise of a known error kind even without denominators"
"$S/bench.sh" candidate-3 --reserve >/dev/null && "$S/bench.sh" candidate-3 --result 'pass=true score=20000 errors=map[25:4,27:1]' >/dev/null
"$S/evaluate.sh" >/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["decision"]=="inconclusive" and d["nextAction"]=="investigate" and "never showed" in d["reason"], d' "$d/decision.json" || fail "v3 blocks on an error family the baseline never showed"
"$S/experiment.sh" record "v3 reject" >/dev/null
[ "$(state DEPLOYED_REV)" = "$(state STABLE_REV)" ] || fail "stable back after v3 reject"

echo "== observe: slow-log digest aggregator"
out=$(python3 "$PLUGIN/scripts/slowlog_digest.py" "$PLUGIN/tests/fixtures/mysql-slow.log")
printf '%s\n' "$out" | grep -q $'^0.00\t2\t0.60\t2000\t2\tSELECT \* FROM users WHERE name = ?$' || fail "slow-log rows aggregated by normalized text"
printf '%s\n' "$out" | grep -q 'VALUES (...) /\* , ... \*/' || fail "multi-row insert collapsed like a performance_schema digest"
printf '%s\n' "$out" | grep -q 'tag_id IN (...)' || fail "IN list collapsed"
printf '%s\n' "$out" | grep -qv 'SET timestamp' || fail "SET timestamp lines dropped"
printf '# observation: t\n\n## MySQL statement digests by total time (slow log)\n%s\n\n## requests by method, path\n900 GET /api/user/:id/icon 200\n\n## secondary indexes present\nusers.PRIMARY(id)\n' "$out" > "$T/observe-slow.txt"
"$S/knowledge.sh" match "$T/observe-slow.txt" | grep -q "observation: 5 digests, 1 request rows" || fail "matcher parses a slow-log dump"

echo "== status"
"$S/status.sh" >/dev/null
echo "all tests passed"
