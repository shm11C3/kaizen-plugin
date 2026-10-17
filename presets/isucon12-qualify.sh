# ISUCON12 予選 (ISUPORTS) practice preset for the aws-isucon AMI.
# `.kaizen/config.sh` sources this file first, then sets APP_HOST(S),
# BENCH_HOST and the private IPs. Every value here can be overridden after
# the source line. Values were read from the servers themselves
# (/home/isucon/webapp, isuports.service, /etc/nginx) and the benchmarker
# help on the bench host; there is no contest manual for this practice.

PROBLEM=isucon12-qualify
REMOTE_APP_DIR=/home/isucon/webapp
# Directories under the project root that deploy.sh pushes to REMOTE_APP_DIR.
# tenant_db/ (per-tenant SQLite files, restored by /initialize) and
# docker-compose-go.yml stay on the server as copied.
LOCAL_SYNC_PATHS="go sql"
# Patterns are anchored at the synced directory: go/isuports (a binary if
# someone runs make on the host) and sql/admin/90_data.sql (160 MB initial
# MySQL dump, ignored by the app's own .gitignore) must survive --delete.
SYNC_EXCLUDES="--exclude /isuports --exclude /admin/90_data.sql"
RSYNC_PATH="sudo -u isucon rsync"
# The app is a docker compose service: isuports.service runs
# `docker compose -f docker-compose-go.yml up --build` in /home/isucon/webapp.
# The image (go/Dockerfile) only COPYs the sources; the container's CMD is
# `go run ./cmd/isuports/main.go`, so the compile happens at container
# start (GOCACHE is on a mounted volume, so it is incremental). BUILD_CMD
# refreshes the image layers so the restart's --build is a cache hit. The
# compose plugin is installed for the isucon user only (root has none), so
# build as isucon.
# Measured on isu12 (2 vCPU): build ~5 s, restart until the first HTTP
# answer ~20-40 s; HEALTH_RETRIES covers a cold compile.
# unattended-upgrades replaced docker.io with 29.x. Until the reboot the old
# daemon (API 1.41) kept running and the new CLI refused to negotiate down;
# after the reboot the new daemon (minimum API 1.44) refuses the compose
# plugin's default 1.42. 1.44 is accepted by both the daemon and compose
# v2.6.1; isuports.service gets the same value through
# etc/systemd/system/isuports.service.d/ in the project's overlay.
DOCKER_ENV='DOCKER_API_VERSION=1.44'
BUILD_CMD="sudo -i -u isucon bash -c 'cd ~/webapp && $DOCKER_ENV docker compose -f docker-compose-go.yml build'"
RESTART_CMD='sudo systemctl restart isuports.service'
SERVICE_NAME=isuports.service
# Any HTTP answer (401 without a cookie) means the process is up; the
# benchmarker checks correctness.
HEALTH_CMD='curl -s -o /dev/null -m 3 http://127.0.0.1:3000/api/me'
HEALTH_RETRIES=240
# <project>/etc/<dir>/... lands at /etc/<dir>/... on every host; the mapped
# service restarts. (MySQL 8.0 and nginx run on the host, not in docker.)
OVERLAY_DIR=etc
OVERLAY_SERVICES="mysql:mysql.service nginx:nginx.service systemd:daemon-reload"
VERIFY_EXCLUDE_REGEX='\.gz$'

# Observation sources.
ACCESS_LOG=/var/log/nginx/access.log
# `sudo mysql` alone is refused (root@localhost needs a password); the
# Debian maintenance account can read and truncate performance_schema.
MYSQL_CMD="sudo mysql --defaults-file=/etc/mysql/debian.cnf"
DB_NAME=isuports
# ids in URLs are hex from the id_generator table (9fa5252c, 583785db4, ...)
# or the literal 0000000000 the benchmarker uses for "does not exist".
PATH_ID_REGEX='/[0-9a-f]{8,}'
# Most of this problem's queries go to per-tenant SQLite files and are
# invisible to performance_schema. The extra evidence is the app's own
# request log: echo's JSON logger writes every request with its latency to
# the container's stdout. OBSERVE_RESET_CMD truncates that log on reset so
# the dump covers exactly one benchmark; OBSERVE_EXTRA_CMD aggregates it
# per (method, path with ids normalized, status) sorted by total latency.
# To see the SQLite statements themselves, set ISUCON_SQLITE_TRACE_FILE in
# go/Dockerfile (ENV) for one observation run; it costs throughput, so not
# in the baseline.
OBSERVE_RESET_CMD="sudo truncate -s0 \"\$(sudo $DOCKER_ENV docker inspect --format={{.LogPath}} webapp-webapp-1)\""
OBSERVE_EXTRA_CMD="sudo $DOCKER_ENV docker logs webapp-webapp-1 2>&1 | python3 -c \"\$(echo aW1wb3J0IHN5cyxqc29uLHJlLGNvbGxlY3Rpb25zCmFnZz1jb2xsZWN0aW9ucy5kZWZhdWx0ZGljdChsYW1iZGE6WzAsMC4wLDAuMF0pCmZvciBsIGluIHN5cy5zdGRpbjoKICAgIGlmIG5vdCBsLnN0YXJ0c3dpdGgoJ3sidGltZSInKTogY29udGludWUKICAgIHRyeTogZD1qc29uLmxvYWRzKGwpCiAgICBleGNlcHQgRXhjZXB0aW9uOiBjb250aW51ZQogICAgdT1yZS5zdWIocidcPy4qJywnJyxkLmdldCgndXJpJywnJykpOyB1PXJlLnN1YihyJy9bMC05YS1mXXs4LH0nLCcvOmlkJyx1KQogICAgYT1hZ2dbKGQuZ2V0KCdtZXRob2QnKSx1LGQuZ2V0KCdzdGF0dXMnKSldOyBtcz1kLmdldCgnbGF0ZW5jeScsMCkvMWU2CiAgICBhWzBdKz0xOyBhWzFdKz1tczsgYVsyXT1tYXgoYVsyXSxtcykKcHJpbnQoJ2NvdW50XHRzdW1fbXNcdGF2Z19tc1x0bWF4X21zXHRtZXRob2QgcGF0aCBzdGF0dXMnKQpmb3IgKG0sdSxzKSwobix0LG14KSBpbiBzb3J0ZWQoYWdnLml0ZW1zKCksa2V5PWxhbWJkYSBrdjota3ZbMV1bMV0pWzoyNV06CiAgICBwcmludChmJ3tufVx0e3Q6LjBmfVx0e3QvbjouMWZ9XHR7bXg6LjBmfVx0e219IHt1fSB7c30nKQo= | base64 -d)\""

# Practice: the benchmarker is a binary on BENCH_HOST (/home/isucon/bench).
# It calls /initialize first (30 s timeout), runs 60 s of load, then the
# consistency checks. A full run takes about 90 s plus prepare.
BENCH_MODE=ssh
# The AMI runs unattended-upgrades on first boot (~25 min at half a core,
# with mysql-server, docker.io, nginx modules and libc replaced and mysqld
# restarted mid-benchmark); no sample while it runs.
# The [e] keeps pgrep -f from matching the remote shell whose command line holds this pattern.
BENCH_PRECHECK_CMD='! pgrep -f "/usr/bin/unattended-upgrad[e]" >/dev/null && ! systemctl is-active --quiet apt-daily-upgrade.service && ! pgrep -x dpkg >/dev/null'
bench_command() {
  echo "sudo -i -u isucon bash -c 'cd ~/bench && ./bench -target-addr ${APP_PRIVATE_IP}:443 -target-url https://t.isucon.local'"
}

# parse_bench <log>: print "pass score errors" from the final lines, or fail
# when the log has no result. The result block looks like
#   Error 0 (Critical:0)
#   PASSED: true
#   SCORE: 1859 (+1859 0(0%))
parse_bench() {
  local pass score errors
  pass=$(sed -n 's/.*PASSED: \([a-z]*\).*/\1/p' "$1" | tail -1)
  score=$(sed -n 's/.*SCORE: \([0-9]*\).*/\1/p' "$1" | tail -1)
  [ -n "$pass" ] && [ -n "$score" ] || return 1
  errors=$(sed -n 's/.*Error \([0-9]*\) (Critical:\([0-9]*\)).*/errors=\1,critical=\2/p' "$1" | tail -1)
  case "$errors" in errors=0,critical=0) errors=none ;; esac
  echo "$pass $score ${errors:-none}"
}

# Request denominator for error rates: access-log lines before and after a run.
REQUEST_COUNT_CMD='sudo wc -l < /var/log/nginx/access.log'
