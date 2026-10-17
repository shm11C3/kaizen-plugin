#!/usr/bin/env bash
# observe.sh reset
# observe.sh dump <name>
# Reset or dump the MySQL statement digests (on DB_HOST) and the access-log
# aggregates (on NGINX_HOST). A dump is the evidence a hypothesis cites
# (observe-<name>.txt in the open experiment, or under .kaizen/ when none is
# open); reset before the benchmark whose load the dump should describe.
# Extra evidence (pprof, alp with a route pattern, slow log) goes through
# OBSERVE_EXTRA_CMD, a command run on NGINX_HOST whose output is appended.
#
# MYSQL_DIGEST_SOURCE=performance_schema (default) reads
# events_statements_summary_by_digest. That table only sees text-protocol
# statements: an app that runs its queries as server-side prepared
# statements (go-sql-driver without interpolateParams, MySQL 8.0) shows up
# there as COMMIT and a few SELECTs while statement/com/Execute carries the
# real load. The dump prints that count so the blind spot is visible.
# MYSQL_DIGEST_SOURCE=slowlog instead turns the slow log on with
# long_query_time=0 at reset, aggregates it with slowlog_digest.py at dump,
# and turns it off again; the sample taken in between pays the logging cost.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
: "${ACCESS_LOG:=/var/log/nginx/access.log}" "${MYSQL_CMD:=sudo mysql}" "${PATH_ID_REGEX:=/[0-9A-Za-z]{20,}}"
: "${DB_HOST:=$APP_HOST}" "${NGINX_HOST:=${APP_HOSTS%% *}}" "${OBSERVE_EXTRA_CMD:=}" "${MYSQL_DIGEST_SOURCE:=performance_schema}"
case "$MYSQL_DIGEST_SOURCE" in performance_schema|slowlog) ;; *) die "MYSQL_DIGEST_SOURCE must be performance_schema or slowlog" ;; esac
[ -n "${DB_NAME:-}" ] || die "config.sh does not set DB_NAME"

case "${1:-}" in
  reset)
    remote "$DB_HOST" "$MYSQL_CMD -e 'TRUNCATE performance_schema.events_statements_summary_by_digest; TRUNCATE performance_schema.events_statements_summary_global_by_event_name'"
    if [ "$MYSQL_DIGEST_SOURCE" = slowlog ]; then
      slowlog=$(remote "$DB_HOST" "$MYSQL_CMD -N -e 'SELECT @@slow_query_log_file'")
      # mysqld creates the file (as the mysql user) when logging turns on; truncate after that.
      remote "$DB_HOST" "$MYSQL_CMD -e \"SET GLOBAL log_output='FILE'; SET GLOBAL long_query_time=0; SET GLOBAL slow_query_log=1\"; sudo truncate -s0 $slowlog"
    fi
    remote "$NGINX_HOST" "sudo truncate -s0 $ACCESS_LOG"
    echo "observation counters reset (db: $DB_HOST, nginx: $NGINX_HOST, digests: $MYSQL_DIGEST_SOURCE)"
    ;;
  dump)
    name=${2:?observe.sh dump <name>}
    out="$EXP_DIR/observe-$name.txt"
    {
      echo "# observation: $name, taken $(now)"
      echo "# deployed revision: $(deployed_marker "${APP_HOSTS%% *}")  hosts: $APP_HOSTS  db: $DB_HOST"
      echo
      if [ "$MYSQL_DIGEST_SOURCE" = slowlog ]; then
        slowlog=$(remote "$DB_HOST" "$MYSQL_CMD -N -e 'SELECT @@slow_query_log_file'")
        remote "$DB_HOST" "$MYSQL_CMD -e 'SET GLOBAL slow_query_log=0'"
        echo "## MySQL statement digests by total time (slow log with long_query_time=0 on $DB_HOST, every schema, since last reset)"
        remote "$DB_HOST" "sudo python3 - $slowlog" < "$KAIZEN_PLUGIN_ROOT/scripts/slowlog_digest.py"
        remote "$DB_HOST" "sudo truncate -s0 $slowlog" || true
      else
        echo "## MySQL statement digests by total time (performance_schema on $DB_HOST, since last reset)"
        remote "$DB_HOST" "$MYSQL_CMD -e \"SELECT ROUND(SUM_TIMER_WAIT/1e12,2) total_s, COUNT_STAR calls, ROUND(AVG_TIMER_WAIT/1e9,2) avg_ms, SUM_ROWS_EXAMINED rows_examined, SUM_ROWS_SENT rows_sent, LEFT(DIGEST_TEXT,150) query FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME='$DB_NAME' ORDER BY SUM_TIMER_WAIT DESC LIMIT 25\""
        remote "$DB_HOST" "$MYSQL_CMD -N -e \"SELECT CONCAT('# prepared-statement executions since reset (statement/com/Execute, not digested above): ', COUNT_STAR) FROM performance_schema.events_statements_summary_global_by_event_name WHERE EVENT_NAME='statement/com/Execute'\"" || true
      fi
      echo
      echo "## requests by method, path (ids normalized), status ($NGINX_HOST:$ACCESS_LOG)"
      remote "$NGINX_HOST" "sudo awk '{p=\$7; sub(/\\?.*/,\"\",p); gsub(/${PATH_ID_REGEX//\//\\/}/,\"/:id\",p); m=\$6; sub(/^\"/,\"\",m); k=m\" \"p\" \"\$9; c[k]++} END{for(k in c) print c[k], k}' $ACCESS_LOG | sort -rn | head -25"
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
