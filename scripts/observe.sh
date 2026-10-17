#!/usr/bin/env bash
# observe.sh reset
# observe.sh dump <name>
# Reset or dump the MySQL statement digests (on DB_HOST) and the access-log
# aggregates (on NGINX_HOST). A dump is the evidence a hypothesis cites
# (observe-<name>.txt in the open experiment, or under .kaizen/ when none is
# open); reset before the benchmark whose load the dump should describe.
# Extra evidence (pprof, alp with a route pattern, slow log, an app log)
# goes through OBSERVE_EXTRA_CMD, a command run on NGINX_HOST whose output
# is appended; OBSERVE_RESET_CMD, run on the same host by reset, clears that
# source so the extra section covers exactly one benchmark.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
: "${ACCESS_LOG:=/var/log/nginx/access.log}" "${MYSQL_CMD:=sudo mysql}" "${PATH_ID_REGEX:=/[0-9A-Za-z]{20,}}"
: "${DB_HOST:=$APP_HOST}" "${NGINX_HOST:=${APP_HOSTS%% *}}" "${OBSERVE_EXTRA_CMD:=}" "${OBSERVE_RESET_CMD:=}"
[ -n "${DB_NAME:-}" ] || die "config.sh does not set DB_NAME"

case "${1:-}" in
  reset)
    remote "$DB_HOST" "$MYSQL_CMD -e 'TRUNCATE performance_schema.events_statements_summary_by_digest; TRUNCATE performance_schema.events_statements_summary_global_by_event_name'"
    remote "$NGINX_HOST" "sudo truncate -s0 $ACCESS_LOG"
    if [ -n "$OBSERVE_RESET_CMD" ]; then
      remote "$NGINX_HOST" "$OBSERVE_RESET_CMD" || die "OBSERVE_RESET_CMD failed on $NGINX_HOST: $OBSERVE_RESET_CMD"
    fi
    echo "observation counters reset (db: $DB_HOST, nginx: $NGINX_HOST${OBSERVE_RESET_CMD:+, extra source})"
    ;;
  dump)
    name=${2:?observe.sh dump <name>}
    out="$EXP_DIR/observe-$name.txt"
    {
      echo "# observation: $name, taken $(now)"
      echo "# deployed revision: $(deployed_marker "${APP_HOSTS%% *}")  hosts: $APP_HOSTS  db: $DB_HOST"
      echo
      echo "## MySQL statement digests by total time (performance_schema on $DB_HOST, since last reset)"
      remote "$DB_HOST" "$MYSQL_CMD -e \"SELECT ROUND(SUM_TIMER_WAIT/1e12,2) total_s, COUNT_STAR calls, ROUND(AVG_TIMER_WAIT/1e9,2) avg_ms, SUM_ROWS_EXAMINED rows_examined, SUM_ROWS_SENT rows_sent, LEFT(DIGEST_TEXT,150) query FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME='$DB_NAME' ORDER BY SUM_TIMER_WAIT DESC LIMIT 25\""
      echo
      echo "## MySQL statement time by event name (global, since last reset; prepared statements show here as statement/com/Execute even when the digest table has no text for them)"
      remote "$DB_HOST" "$MYSQL_CMD -e \"SELECT EVENT_NAME, COUNT_STAR calls, ROUND(SUM_TIMER_WAIT/1e12,2) total_s, ROUND(AVG_TIMER_WAIT/1e9,2) avg_ms FROM performance_schema.events_statements_summary_global_by_event_name WHERE COUNT_STAR > 0 ORDER BY SUM_TIMER_WAIT DESC LIMIT 8\"" || echo "(not available)"
      echo
      echo "## requests by method, path (ids normalized), status ($NGINX_HOST:$ACCESS_LOG)"
      remote "$NGINX_HOST" "sudo awk '{m=\$6; gsub(/\"/,\"\",m); p=\$7; sub(/\\?.*/,\"\",p); gsub(/${PATH_ID_REGEX//\//\\/}/,\"/:id\",p); k=m\" \"p\" \"\$9; c[k]++} END{for(k in c) print c[k], k}' $ACCESS_LOG | sort -rn | head -25"
      echo
      echo "## secondary indexes present"
      remote "$DB_HOST" "$MYSQL_CMD -N -e \"SELECT CONCAT(TABLE_NAME,'.',INDEX_NAME,'(',GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX),')') FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='$DB_NAME' GROUP BY TABLE_NAME, INDEX_NAME ORDER BY 1\""
      if [ -n "$OBSERVE_EXTRA_CMD" ]; then
        echo
        echo "## extra ($OBSERVE_EXTRA_CMD)"
        remote "$NGINX_HOST" "$OBSERVE_EXTRA_CMD" || echo "(extra command failed)"
      fi
    } > "$out"
    echo "$out"
    ;;
  *) die "usage: observe.sh reset | dump <name>" ;;
esac
