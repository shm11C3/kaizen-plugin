# ISUCON14 (ISURIDE) practice preset for the aws-isucon AMI. `.kaizen/config.sh`
# sources this file first, then sets APP_HOST(S), BENCH_HOST and private IPs.
# Every value here can be overridden after the source line. For a new
# contest copy templates/preset.sh.example instead and fill it from the manual.

PROBLEM=isucon14
REMOTE_APP_DIR=/home/isucon/webapp
# Directories under the project root that deploy.sh pushes to REMOTE_APP_DIR.
LOCAL_SYNC_PATHS="go sql"
# The compiled binary lives next to the sources; never delete it on sync.
SYNC_EXCLUDES="--exclude isuride"
RSYNC_PATH="sudo -u isucon rsync"
BUILD_CMD='sudo -i -u isucon bash -c "cd ~/webapp/go && go build -o isuride ."'
# The matcher reads ISUCON_MATCHING_INTERVAL from env.sh; a systemd drop-in in
# etc/systemd/system/isuride-matcher.service.d/ overrides it, so restart both.
RESTART_CMD='sudo systemctl daemon-reload && sudo systemctl restart isuride-go.service isuride-matcher.service'
SERVICE_NAME=isuride-go.service
# Any HTTP answer means the process is up; the benchmarker checks correctness.
HEALTH_CMD='curl -s -o /dev/null -m 3 http://127.0.0.1:8080/api/app/users'
HEALTH_RETRIES=20
# <project>/etc/<dir>/... lands at /etc/<dir>/... on every host (and
# <project>/etc-<host>/ on that host only); the mapped service restarts.
OVERLAY_DIR=etc
OVERLAY_SERVICES="mysql:mysql.service nginx:nginx.service systemd:daemon-reload"
# The initial data dump is large and never edited; skip it in verify.sh.
VERIFY_EXCLUDE_REGEX='\.gz$'

# Observation sources.
ACCESS_LOG=/var/log/nginx/access.log
MYSQL_CMD="sudo mysql"
DB_NAME=isuride
PATH_ID_REGEX='/01[0-9A-Z]{24}'

# Practice: the benchmarker is a binary on BENCH_HOST that also serves as the
# payment mock. On contest day set BENCH_MODE=manual and use the portal.
BENCH_MODE=ssh
BENCH_SECONDS=60
bench_command() {
  echo "sudo -i -u isucon ./bench run --addr ${APP_PRIVATE_IP}:443 --target https://isuride.xiv.isucon.net --payment-url http://${BENCH_PRIVATE_IP}:12346 --payment-bind-port 12346 -t ${BENCH_SECONDS}"
}

# parse_bench <log>: print "pass score errors" from the final result line, or
# fail when the log has no result line. slog quotes the error map only when
# it contains spaces: map[] vs "map[25:5 30:1]".
parse_bench() {
  local line pass score errors
  line=$(grep -o 'msg=結果 pass=[a-z]* スコア=[0-9]*' "$1" | tail -1) || true
  [ -n "$line" ] || return 1
  pass=$(printf '%s' "$line" | sed -n 's/.*pass=\([a-z]*\).*/\1/p')
  score=$(printf '%s' "$line" | sed -n 's/.*スコア=\([0-9]*\).*/\1/p')
  errors=$(sed -n 's/.*種別エラー数="\{0,1\}\(map\[[^]]*\]\).*/\1/p' "$1" | tail -1 | tr ' ' ',')
  echo "$pass $score ${errors:-none}"
}
