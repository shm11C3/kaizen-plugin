#!/usr/bin/env bash
# Shared helpers for the kaizen scripts. Sourced, never executed.
#
# Everything the loop knows lives under <project>/.kaizen/:
#   config.sh            operator-written target configuration (sources a preset)
#   state.env            key=value, written only by these scripts
#   baseline/<rev>/      benchmark samples of a stable revision
#   experiments/<id>/    manifest.json, observe-*.txt, bench-*.json/.log,
#                        decision.json (evaluate.sh), record.json, timeline.tsv
#   log.md               one row per closed experiment
# The scripts are the only writers of state.env, decision.json and record.json,
# which is what lets the hooks trust them.
#
# Hosts: APP_HOSTS (space-separated SSH aliases; default APP_HOST) all receive
# the same application directories and the common etc/ overlay; a host also
# receives <OVERLAY_DIR>-<host>/ when that directory exists. The benchmark is
# either started over SSH on BENCH_HOST (BENCH_MODE=ssh, practice) or run by
# the operator on the contest portal and recorded with --result
# (BENCH_MODE=manual, contest day).

set -euo pipefail
# KAIZEN_TRACE=1 traces every script, for debugging a silent non-zero exit.
[ -z "${KAIZEN_TRACE:-}" ] || set -x

KAIZEN_PLUGIN_ROOT="${KAIZEN_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export KAIZEN_PLUGIN_ROOT
KAIZEN_PROJECT="${KAIZEN_PROJECT:-$(pwd)}"
KAIZEN_DIR="$KAIZEN_PROJECT/.kaizen"
STATE_FILE="$KAIZEN_DIR/state.env"
LOCK_DIR="$KAIZEN_DIR/bench.lock"

# Friction: every refusal (die) and every unexpected command failure (ERR
# trap) is appended to .kaizen/friction.jsonl so the retro step can turn
# what broke on real hosts into plugin fixes without anyone taking notes.
friction_log() { # <kind> <message> [<command>]
  [ -d "${KAIZEN_DIR:-}" ] || return 0
  python3 - "$KAIZEN_DIR/friction.jsonl" "$1" "$(basename "${BASH_SOURCE[$((${#BASH_SOURCE[@]} - 1))]:-$0}")" "${EXP:-}" "$2" "$(printf '%s' "${3:-}" | head -c 200)" "$(now)" <<'PY' 2>/dev/null || true
import json, sys
path, kind, script, exp, message, command, ts = sys.argv[1:]
with open(path, "a") as f:
    f.write(json.dumps({"ts": ts, "kind": kind, "script": script, "experiment": exp or None,
                        "message": message, "command": command or None, "resolved": False}, ensure_ascii=False) + "\n")
PY
}
die() { friction_log die "$*"; echo "kaizen: $*" >&2; exit 2; }
log() { echo "kaizen: $*" >&2; }
friction_err() { # <command> <status>
  # 141 is SIGPIPE: the reader of our output went away (status.sh | head); not our defect.
  [ "$2" = 141 ] || friction_log err "command failed with status $2" "$1"
}
set -E
trap 'friction_err "$BASH_COMMAND" $?' ERR
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
stamp() { date -u +%Y%m%dT%H%M%SZ; }
epoch() { date +%s; }
short() { printf '%s' "$1" | cut -c1-7; }
to_epoch() { python3 -c 'import sys,datetime; print(int(datetime.datetime.strptime(sys.argv[1],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()))' "$1"; }

load_config() {
  [ -f "$KAIZEN_DIR/config.sh" ] || die "no $KAIZEN_DIR/config.sh (run /kaizen:setup)"
  # shellcheck disable=SC1091
  . "$KAIZEN_DIR/config.sh"
  local name
  for name in APP_HOST REMOTE_APP_DIR LOCAL_SYNC_PATHS BUILD_CMD RESTART_CMD HEALTH_CMD; do
    [ -n "${!name:-}" ] || die "config.sh does not set $name"
  done
  : "${APP_HOSTS:=$APP_HOST}" "${BENCH_MODE:=ssh}" "${BENCH_HOST:=}"
  case "$BENCH_MODE" in
    ssh)
      [ -n "$BENCH_HOST" ] || die "BENCH_MODE=ssh needs BENCH_HOST"
      declare -f bench_command >/dev/null || die "config.sh does not define bench_command()"
      declare -f parse_bench >/dev/null || die "config.sh does not define parse_bench()"
      ;;
    manual) ;;
    *) die "BENCH_MODE must be ssh or manual" ;;
  esac
  : "${SYNC_EXCLUDES:=}" "${RSYNC_PATH:=}" "${SSH_CONFIG:=}" "${HEALTH_RETRIES:=20}"
  : "${STABLE_BRANCH:=main}" "${OVERLAY_DIR:=etc}" "${OVERLAY_SERVICES:=}" "${VERIFY_EXCLUDE_REGEX:=\.gz$}"
  : "${MIN_IMPROVEMENT_BP:=300}" "${MAX_BENCH_PER_EXP:=6}" "${MAX_EXP_MINUTES:=30}" "${MAX_EXP_PER_HOUR:=6}"
  : "${MIN_SAMPLES:=2}" "${BASELINE_MAX_AGE_MINUTES:=60}" "${CORRECTNESS_ERROR_TYPES:=}"
  # v2: practice, two samples per side, error rates need request denominators.
  # v3: contest (opt-in), sequential by effect size against the baseline spread.
  : "${EVALUATION_RULE:=v2}" "${REQUEST_COUNT_CMD:=}" "${NGINX_HOST:=${APP_HOSTS%% *}}"
  case "$EVALUATION_RULE" in v2|v3) ;; *) die "EVALUATION_RULE must be v2 or v3" ;; esac
  : "${MAX_BENCH_TOTAL:=120}" "${MAX_BENCH_PER_HOUR:=30}" "${RECOVERY_BENCH_RESERVE:=1}"
  : "${RESOURCE_HOSTS:=$APP_HOSTS}" "${RESOURCE_FINGERPRINT_CMD:=}" "${RECOVERY_CMD:=}"
  : "${RESOURCE_PATHS:=sql $OVERLAY_DIR}"
  if [ -n "$RESOURCE_FINGERPRINT_CMD" ] || [ -n "$RECOVERY_CMD" ]; then
    [ -n "$RESOURCE_FINGERPRINT_CMD" ] && [ -n "$RECOVERY_CMD" ] || die "configure both RESOURCE_FINGERPRINT_CMD and RECOVERY_CMD"
  fi
  mkdir -p "$KAIZEN_DIR/baseline" "$KAIZEN_DIR/experiments"
  EXP=$(state_get CURRENT_EXPERIMENT)
  if [ -n "$EXP" ]; then EXP_DIR="$KAIZEN_DIR/experiments/$EXP"; else EXP_DIR="$KAIZEN_DIR"; fi
  if [ -f "$KAIZEN_DIR/stable-sync-pending.json" ] && [ "${KAIZEN_SYNC_ACTIVE:-0}" != 1 ]; then
    die "sandbox stable sync is pending; use owned target stable-sync --rollback before other operations"
  fi
}

state_get() {
  [ -f "$STATE_FILE" ] || return 0
  sed -n "s/^$1=//p" "$STATE_FILE" | tail -1
}

state_set() {
  touch "$STATE_FILE"
  { grep -v "^$1=" "$STATE_FILE" || true; echo "$1=$2"; } > "$STATE_FILE.tmp"
  mv "$STATE_FILE.tmp" "$STATE_FILE"
}

# record_step <phase> <subject> <seconds> <status>: one timeline row, so the
# record shows how long each phase took without the agent timing anything.
record_step() {
  printf '%s\t%s\t%s\t%ss\t%s\n' "$(now)" "$1" "$2" "$3" "$4" >> "$EXP_DIR/timeline.tsv"
}

# remote <host> <command>: run a shell command on a host. With
# KAIZEN_FAKE_REMOTE set (tests), run it locally inside <fake>/<host>.
remote() {
  local host=$1; shift
  if [ -n "${KAIZEN_FAKE_REMOTE:-}" ]; then
    mkdir -p "$KAIZEN_FAKE_REMOTE/$host"
    (cd "$KAIZEN_FAKE_REMOTE/$host" && FAKE_HOST="$host" bash -c "$*")
  else
    # shellcheck disable=SC2086
    ssh ${SSH_CONFIG:+-F "$SSH_CONFIG"} -o BatchMode=yes "$host" "$*"
  fi
}

ssh_command() {
  if [ -n "$SSH_CONFIG" ]; then echo "ssh -F $SSH_CONFIG"; else echo "ssh"; fi
}

# sync_dir <local-dir> <host> <remote-dir>: mirror an application directory.
sync_dir() {
  local src=$1 host=$2 dst=$3
  if [ -n "${KAIZEN_FAKE_REMOTE:-}" ]; then
    mkdir -p "$KAIZEN_FAKE_REMOTE/$host/$dst"
    # shellcheck disable=SC2086
    rsync -a --delete $SYNC_EXCLUDES "$src/" "$KAIZEN_FAKE_REMOTE/$host/$dst/"
  else
    # shellcheck disable=SC2086
    rsync -a --delete $SYNC_EXCLUDES -e "$(ssh_command)" ${RSYNC_PATH:+--rsync-path="$RSYNC_PATH"} "$src/" "$host:$dst/"
  fi
}

# overlay_root <host>: where "/<OVERLAY_DIR>" is on that host: the real root,
# or the fake host directory under tests.
overlay_root() {
  if [ -n "${KAIZEN_FAKE_REMOTE:-}" ]; then echo "$KAIZEN_FAKE_REMOTE/$1"; else echo ""; fi
}

# sync_overlay <local-dir> <host>: copy configuration files into the host's
# /<OVERLAY_DIR> as root. Never deletes; prints the changed paths.
sync_overlay() {
  local src=$1 host=$2 dst
  dst="$(overlay_root "$host")/$OVERLAY_DIR"
  # rsync itemizes a sent file as "<f..." and a locally copied one as ">f...";
  # ownership is not preserved so /etc files belong to root, not to the
  # operator's uid.
  if [ -n "${KAIZEN_FAKE_REMOTE:-}" ]; then
    mkdir -p "$dst"
    rsync -ai --no-owner --no-group "$src/" "$dst/" | awk '/^[<>]f/ {print $2}'
  else
    rsync -ai --no-owner --no-group -e "$(ssh_command)" --rsync-path="sudo rsync" "$src/" "$host:$dst/" | awk '/^[<>]f/ {print $2}'
  fi
}

acquire_bench_lock() {
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    die "a benchmark or deploy is already running (lock $LOCK_DIR; rmdir it only if you are sure none is)"
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
}

# deployed_marker <host>: the revision the host says it runs.
deployed_marker() {
  remote "$1" "cat $REMOTE_APP_DIR/.deployed-revision 2>/dev/null || echo unknown"
}

# count_matches <glob...>: number of existing paths; safe under pipefail.
count_matches() {
  local n=0 f
  for f in "$@"; do [ -e "$f" ] && n=$((n + 1)); done
  echo "$n"
}

git_rev() { git -C "$KAIZEN_PROJECT" rev-parse --verify "$1^{commit}" 2>/dev/null; }
git_head() { git -C "$KAIZEN_PROJECT" rev-parse HEAD; }
# The loop's own records under .kaizen/ change during an experiment and may be
# tracked; only application files count as a dirty tree.
git_dirty() { [ -n "$(git -C "$KAIZEN_PROJECT" status --porcelain --untracked-files=no -- . ':(exclude).kaizen')" ]; }

# plugin_revision: which plugin measured a sample. Recorded in bundles and
# samples for the retro, never part of a bundle's identity: the plugin is
# expected to change during a contest (retro fixes) without invalidating
# the stable it measures.
plugin_revision() {
  local rev dirty version
  rev=$(git -C "$KAIZEN_PLUGIN_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
  dirty=$(git -C "$KAIZEN_PLUGIN_ROOT" status --porcelain 2>/dev/null | grep -q . && echo "-dirty" || true)
  version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version","?"))' "$KAIZEN_PLUGIN_ROOT/.claude-plugin/plugin.json" 2>/dev/null || echo "?")
  echo "$version@$rev$dirty"
}

# config_digest: the measurement conditions a stable bundle is bound to:
# which hosts run what, how it is built, restarted, probed, recovered and
# benchmarked. Budgets, thresholds, observation sources, comments and the
# plugin's own files are not conditions: changing them must not retire a
# bundle. Resolved values are hashed, so an edited preset only matters when
# it changes one of these.
config_digest() {
  local bench
  bench=$(declare -f bench_command >/dev/null 2>&1 && bench_command 2>/dev/null || true)
  printf '%s\n' "$APP_HOSTS" "$RESOURCE_HOSTS" "$BENCH_HOST" "$BENCH_MODE" "$REMOTE_APP_DIR" \
    "$LOCAL_SYNC_PATHS" "$SYNC_EXCLUDES" "$RSYNC_PATH" "$OVERLAY_DIR" "$OVERLAY_SERVICES" "$RESOURCE_PATHS" \
    "$BUILD_CMD" "$RESTART_CMD" "$HEALTH_CMD" "$RESOURCE_FINGERPRINT_CMD" "$RECOVERY_CMD" "$SSH_CONFIG" \
    "$bench" "$(declare -f parse_bench 2>/dev/null || true)" \
    "$NGINX_HOST" "$REQUEST_COUNT_CMD" "$(declare -f parse_bench_requests 2>/dev/null || true)" |
    python3 "$KAIZEN_PLUGIN_ROOT/scripts/resources.py" config
}

# A source ID identifies the denominator's method, not its changing counter value.
# Keep command/parser hashes in samples rather than copying command contents.
request_source() {
  python3 - "$1" "$NGINX_HOST" "$REQUEST_COUNT_CMD" "$(declare -f parse_bench_requests 2>/dev/null || true)" <<'PY'
import hashlib,json,sys
method,host,command,parser=sys.argv[1:]
source={'method':method}
digest=lambda text: hashlib.sha256(text.encode()).hexdigest()
if method=='counter-delta': source.update(host=host,commandHash=digest(command))
if method=='bench-parser': source['parserHash']=digest(parser)
source['id']=digest(json.dumps(source,sort_keys=True))
print(json.dumps(source))
PY
}

# Unavailable, noisy or failed counters remain unknown; never join unrelated digits.
request_count() {
  local value
  value=$(remote "$NGINX_HOST" "$REQUEST_COUNT_CMD" 2>/dev/null) || return 0
  printf '%s' "$value" | python3 -c 'import re,sys; s=sys.stdin.read().strip(); print(int(s)) if re.fullmatch(r"[0-9]+",s) else None'
}

request_delta() {
  python3 - "$1" "$2" <<'PY'
import sys
a,b=sys.argv[1:]
if a.isdecimal() and b.isdecimal() and int(b)>=int(a): print(int(b)-int(a))
PY
}

resource_fingerprints() {
  local host value
  [ -n "$RESOURCE_FINGERPRINT_CMD" ] || return 0
  for host in $RESOURCE_HOSTS; do
    value=$(remote "$host" "$RESOURCE_FINGERPRINT_CMD") || die "resource probe failed on $host"
    printf '%s\t%s\n' "$host" "$(printf '%s' "$value" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  done
}

verify_bundle() {
  local stable config_hash fingerprints message
  stable=$(state_get STABLE_REV)
  [ -f "$KAIZEN_DIR/stable-bundle.json" ] || die "stable bundle missing; deploy stable, then stable.sh capture"
  config_hash=$(config_digest) || die "cannot identify target configuration"
  fingerprints=$(resource_fingerprints) || die "cannot probe stable resources"
  message=$(python3 "$KAIZEN_PLUGIN_ROOT/scripts/resources.py" verify "$KAIZEN_DIR/stable-bundle.json" \
    "$stable" "$config_hash" "$fingerprints" 2>&1) || die "stable bundle: $message"
}

verify_bundle_config() {
  local config_hash message
  [ -f "$KAIZEN_DIR/stable-bundle.json" ] || die "stable bundle missing; deploy stable, then stable.sh capture"
  config_hash=$(config_digest) || die "cannot identify target configuration"
  message=$(python3 "$KAIZEN_PLUGIN_ROOT/scripts/resources.py" verify-config "$KAIZEN_DIR/stable-bundle.json" \
    "$(state_get STABLE_REV)" "$config_hash" "" 2>&1) || die "stable bundle: $message"
}

capture_bundle() {
  local paths host config_hash fingerprints
  paths="$LOCAL_SYNC_PATHS $OVERLAY_DIR"
  for host in $APP_HOSTS; do paths="$paths $OVERLAY_DIR-$host"; done
  config_hash=$(config_digest) || die "cannot identify target configuration"
  fingerprints=$(resource_fingerprints) || die "cannot capture stable resources"
  # shellcheck disable=SC2086
  KAIZEN_PLUGIN_REVISION=$(plugin_revision) python3 "$KAIZEN_PLUGIN_ROOT/scripts/resources.py" capture "$KAIZEN_DIR/stable-bundle.json" \
    "$(state_get STABLE_REV)" "$config_hash" "$fingerprints" $paths
}

no_manual_bench() {
  [ ! -f "$KAIZEN_DIR/manual-bench.json" ] || die "a portal benchmark is reserved; record its result or abandon it after confirming it ended"
}

# experiments_started_since <epoch>: how many experiments opened after a time.
experiments_started_since() {
  local since=$1 n=0 f started
  for f in "$KAIZEN_DIR"/experiments/*/manifest.json; do
    [ -f "$f" ] || continue
    started=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("startedAt",""))' "$f")
    [ -n "$started" ] && [ "$(to_epoch "$started")" -ge "$since" ] && n=$((n + 1))
  done
  echo "$n"
}
