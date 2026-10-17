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
m.update(hypothesisId="flush-log", hypothesis="COMMIT waits on fsync", expectedEffect="score up",
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

echo "== status"
"$S/status.sh" >/dev/null
echo "all tests passed"
