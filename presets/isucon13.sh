# ISUCON13 (ISUPipe) practice preset for the aws-isucon AMI. `.kaizen/config.sh`
# sources this file first, then sets APP_HOST(S), BENCH_HOST and private IPs.
# Every value here can be overridden after the source line.
#
# Target layout (from the hosts, not from a manual): the app is
# /home/isucon/webapp/go (binary isupipe, unit isupipe-go.service,
# EnvironmentFile /home/isucon/env.sh), sql/init.sh is what /initialize
# runs (init.sql + initial_*.sql, then ../pdns/init_zone.sh which reloads
# the u.isucon.local zone with ISUCON13_POWERDNS_SUBDOMAIN_ADDRESS from
# env.sh). nginx terminates TLS for *.u.isucon.local on 443 and proxies
# /api to :8080; PowerDNS answers on 53 from the isudns MySQL schema.
#
# Benchmarker from a separate host: env.sh on the app host must carry the
# app host's private IP in ISUCON13_POWERDNS_SUBDOMAIN_ADDRESS (the zone is
# rewritten from it on every /initialize), and the bench resolves through
# the app host (--nameserver) and pretests it directly (--webapp).

PROBLEM=isucon13
REMOTE_APP_DIR=/home/isucon/webapp
# Directories under the project root that deploy.sh pushes to REMOTE_APP_DIR.
LOCAL_SYNC_PATHS="go sql pdns"
# The compiled binary lives next to the sources; never delete it on sync.
SYNC_EXCLUDES="--exclude isupipe"
RSYNC_PATH="sudo -u isucon rsync"
BUILD_CMD='sudo -i -u isucon bash -c "cd ~/webapp/go && go build -o isupipe ."'
RESTART_CMD='sudo systemctl daemon-reload && sudo systemctl restart isupipe-go.service'
SERVICE_NAME=isupipe-go.service
# Any HTTP answer from the app port (main.go listenPort = 8080) means the
# process is up; the benchmarker checks correctness.
HEALTH_CMD='curl -s -o /dev/null -m 3 http://127.0.0.1:8080/api/tag'
HEALTH_RETRIES=20
# <project>/etc/<dir>/... lands at /etc/<dir>/... on every host (and
# <project>/etc-<host>/ on that host only); the mapped service restarts.
OVERLAY_DIR=etc
OVERLAY_SERVICES="mysql:mysql.service nginx:nginx.service powerdns:pdns.service systemd:daemon-reload"
# Nothing large and compressed in this tree, but keep the default.
VERIFY_EXCLUDE_REGEX='\.gz$'

# Observation sources.
ACCESS_LOG=/var/log/nginx/access.log
MYSQL_CMD="sudo mysql"
DB_NAME=isupipe
# URLs carry numeric ids (/api/livestream/123/livecomment) and usernames
# that always contain a digit (kazuya580, UuDuxt1oTg); any alphanumeric
# segment with a digit collapses to /:id, so /api/user/me stays as it is.
PATH_ID_REGEX='/[A-Za-z0-9]*[0-9][A-Za-z0-9]*'
# The Go app runs every parameterized query as a server-side prepared
# statement; performance_schema digests miss those on MySQL 8.0, the slow
# log does not (see observe.sh).
MYSQL_DIGEST_SOURCE=slowlog

# Practice: the benchmarker binary on BENCH_HOST. On contest day set
# BENCH_MODE=manual and use the portal.
BENCH_MODE=ssh
# One run is ~2 min: static check, /initialize (~15s), consistency check
# (~35s), 60s load, final check. The old result.json is removed first so a
# benchmarker that fails to start cannot be mistaken for a sample.
bench_command() {
  # The benchmarker's log goes to a file first so its stderr cannot interleave
  # with the result.json line (seen once: the JSON line had a log line glued on).
  echo "cd /home/isucon && sudo rm -f /tmp/result.json /tmp/bench.log && sudo -i -u isucon ./bench run --enable-ssl --nameserver ${APP_PRIVATE_IP} --webapp ${APP_PRIVATE_IP} --result-path /tmp/result.json > /tmp/bench.log 2>&1; cat /tmp/bench.log; echo; echo '=== result.json'; cat /tmp/result.json; echo"
}

# parse_bench <log>: print "pass score errors" from the result.json the
# benchmarker writes (echoed after the '=== result.json' line), or fail when
# it is missing. result.json: {"pass":bool,"score":int,"messages":[...],
# "language":..,"resolved_count":int}. Error messages start with a bracketed
# kind ("[一般エラー]", "[リクエストタイムアウト]") followed by METHOD /path and
# the detail; the summary lines (名前解決成功数, 売上) are not errors. The errors
# field keeps "kind:METHOD:/path(ids as :id)xN", comma separated.
parse_bench() {
  # The ssh session has been seen to end right after the benchmarker's last
  # log line, before the trailing cat ran (sudo use_pty on Ubuntu 22.04 is
  # the suspect): when the marker is missing, fetch result.json from the
  # bench host and append it to the log so the sample stays reproducible.
  # The file was removed before the run, so a stale result cannot leak in.
  if ! grep -q '^=== result.json' "$1" && [ -n "${BENCH_HOST:-}" ] && declare -f remote >/dev/null; then
    { echo '=== result.json (fetched after the run)'; remote "$BENCH_HOST" "cat /tmp/result.json"; } >> "$1" 2>/dev/null || true
  fi
  python3 - "$1" <<'PY'
import json, re, sys
from collections import Counter
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
_, sep, tail = text.rpartition("=== result.json")
if not sep:
    sys.exit(1)
lines = [l for l in tail.splitlines() if l.startswith("{")]
try:
    r = json.loads(lines[0])
except (IndexError, json.JSONDecodeError):
    sys.exit(1)
kinds = Counter()
for m in r.get("messages") or []:
    g = re.match(r"\[([^\]]+)\]\s*(?:(GET|POST|PUT|DELETE|PATCH)\s+)?(\S*)", str(m))
    if not g:
        continue
    path = re.sub(r"/[0-9]+", "/:id", g.group(3))
    path = re.sub(r"/user/[^/]+", "/user/:name", path)
    path = path.split("?")[0].rstrip(":")
    kinds[":".join(x for x in (g.group(1), g.group(2), path) if x)] += 1
errors = ",".join(f"{k}x{n}" for k, n in sorted(kinds.items())) or "none"
print("true" if r.get("pass") else "false", int(r.get("score", 0)), errors)
PY
}

# Request denominator for error rates: access-log lines before and after a run.
REQUEST_COUNT_CMD='sudo wc -l < /var/log/nginx/access.log'
