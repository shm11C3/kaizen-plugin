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
  python3 - "$KAIZEN_DIR/friction.jsonl" "$1" "$(basename "${BASH_SOURCE[$((${#BASH_SOURCE[@]} - 1))]:-$0}")" "${EXP:-}" "$2" "${3:-}" "$(now)" <<'PY' 2>/dev/null || true
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
  friction_log err "command failed with status $2" "$1"
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
  mkdir -p "$KAIZEN_DIR/baseline" "$KAIZEN_DIR/experiments"
  EXP=$(state_get CURRENT_EXPERIMENT)
  if [ -n "$EXP" ]; then EXP_DIR="$KAIZEN_DIR/experiments/$EXP"; else EXP_DIR="$KAIZEN_DIR"; fi
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
  if [ -n "${KAIZEN_FAKE_REMOTE:-}" ]; then
    mkdir -p "$dst"
    rsync -ai "$src/" "$dst/" | awk '/^>f/ {print $2}'
  else
    rsync -ai -e "$(ssh_command)" --rsync-path="sudo rsync" "$src/" "$host:$dst/" | awk '/^>f/ {print $2}'
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
git_dirty() { [ -n "$(git -C "$KAIZEN_PROJECT" status --porcelain --untracked-files=no)" ]; }

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
