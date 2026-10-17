#!/usr/bin/env bash
# End-to-end test of the loop against a fake remote: two app hosts, a fake
# benchmarker, shims for sudo/systemctl/md5sum. Exercises setup, baseline,
# a promoted experiment (with an etc/ overlay change), a correctness-failed
# experiment with recovery, the budget, and the hook guard.
set -euo pipefail

PLUGIN=$(cd "$(dirname "$0")/.." && pwd)
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
PROBLEM=test
RETRO_BLOCK_AFTER=1000
EOF

S="$PLUGIN/scripts"
fail() { echo "FAIL: $*" >&2; exit 1; }
expect_fail() { if "$@" >/dev/null 2>&1; then fail "expected failure: $*"; fi; }
state() { sed -n "s/^$1=//p" .kaizen/state.env | tail -1; }

echo "== setup: pin stable, deploy, recovery drill"
printf 'STABLE_REV=%s\n' "$(git rev-parse main)" > .kaizen/state.env
expect_fail "$S/bench.sh" baseline                    # nothing deployed yet
"$S/deploy.sh" main >/dev/null
[ "$(state DEPLOYED_REV)" = "$(git rev-parse main)" ] || fail "DEPLOYED_REV after deploy"
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu2/webapp/.deployed-revision")" = "$(git rev-parse main)" ] || fail "marker on isu2"
[ "$(cat "$KAIZEN_FAKE_REMOTE/isu1/etc/mysql/my.cnf")" = "innodb_flush_log_at_trx_commit=1" ] || fail "overlay synced"
"$S/recover.sh" >/dev/null
"$S/verify.sh" main >/dev/null

echo "== baseline"
expect_fail "$S/bench.sh" candidate                   # no experiment open
"$S/bench.sh" baseline >/dev/null
"$S/bench.sh" baseline-2 >/dev/null
[ "$(ls .kaizen/baseline/"$(git rev-parse main)"/*.json | wc -l | tr -d ' ')" = 2 ] || fail "baseline samples filed"

echo "== precheck: a busy host refuses a sample; forget-baseline retires contaminated samples"
echo "BENCH_PRECHECK_CMD='test ! -f busy.marker'" >> .kaizen/config.sh
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
"$S/experiment.sh" new flush-log >/dev/null
[ "$(git branch --show-current)" = "exp/001-flush-log" ] || fail "experiment branch"
echo 2000 > go/score
echo 'innodb_flush_log_at_trx_commit=2' > etc/mysql/my.cnf
git commit -qam "candidate: flush log every second"
expect_fail "$S/deploy.sh" HEAD                        # manifest not filled
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
"$S/bench.sh" candidate-2 >/dev/null
"$S/evaluate.sh" >/dev/null
[ "$(python3 -c 'import json; print(json.load(open(".kaizen/experiments/001-flush-log/decision.json"))["decision"])')" = promote ] || fail "rule should promote"
"$S/experiment.sh" record "indexes and flush setting, +100%" >/dev/null
cand=$(git rev-parse exp/001-flush-log)
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

echo "== manual bench mode"
cat >> .kaizen/config.sh <<'EOF'
BENCH_MODE=manual
EOF
expect_fail "$S/bench.sh" baseline-3                   # needs --result
"$S/bench.sh" baseline-3 --result 'pass=true score=2100 errors=none' --seconds 65 >/dev/null
python3 -c 'import json,glob; s=[json.load(open(p)) for p in glob.glob(".kaizen/baseline/*/bench-*baseline-3.json")]; assert s and s[0]["score"]==2100 and s[0]["mode"]=="manual"' || fail "manual sample"

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
"$S/bench.sh" candidate --result 'pass=true score=2600 errors=none' >/dev/null
"$S/evaluate.sh" >/dev/null
"$S/experiment.sh" record "stop check" >/dev/null
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

echo "== observe: reset clears the extra source, dump appends the extra command"
cat >> .kaizen/config.sh <<'EOF2'
MYSQL_CMD=true
DB_NAME=test
ACCESS_LOG=access.log
OBSERVE_RESET_CMD='echo cleared > reset.marker'
OBSERVE_EXTRA_CMD='echo extra-evidence-line'
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

echo "== status"
"$S/status.sh" >/dev/null
echo "all tests passed"
