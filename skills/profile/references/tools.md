# Read the selected tool's output

Keep the exact command, tool version, source revision, collection window and raw
file. These are recipes to adapt to the project's real format, not a requirement
to install every tool.

## Access time: alp

Use existing JSON/LTSV timing fields. For nginx, `$request_time` is whole request
elapsed time and `$upstream_response_time` is a different interval; don't mix them.
Choose the field that answers the question. Without duration fields, report counts
only and add timing via an owned configuration candidate if that has payoff.
Avoid logging cookies, bodies, query strings or literal IDs. Normalize routes at
collection or with explicit alp matching groups; a generic `{id}` pattern is not
inferred by alp.

```bash
alp --version
alp json --file access.jsonl --sort sum --reverse --format json --nosave-pos
alp json --file access.jsonl --sort avg --reverse --format json --nosave-pos
alp json --file access.jsonl --sort count --reverse --format json --nosave-pos
```

Check supported formats with the installed `alp json --help`; use TSV when JSON
output is unavailable. Use `--nosave-pos` for repeatable analysis of the same
captured file; a saved cursor can make a second run read no records.
Rank total time to find aggregate cost, then inspect count
and average to distinguish frequent work from rare slow work. Compare errors and
traffic mix, not averages alone. Long-lived streams have naturally long durations.

Primary source: [alp usage and log formats](https://github.com/tkuchiki/alp).

## SQL: pt-query-digest and EXPLAIN

```bash
pt-query-digest --version
pt-query-digest --output json slow.log > digest.json
```

Analyze a captured copy; collection changes on a shared target use the existing
owner/observe boundary. Fingerprints group query shapes, including prepared
statement workloads not represented faithfully by statement digests. Inspect
query count, total query time, rows examined/sent and the executed plan. Use
EXPLAIN before proposing an index; EXPLAIN ANALYZE executes the statement and
requires suitable isolation. Preserve slowlog collection overhead and avoid raw
query/argument publication. Trace count identifies request ownership; a SQL
digest identifies query shapes. Neither alone proves an optimization's score.

Primary source: [pt-query-digest](https://docs.percona.com/percona-toolkit/pt-query-digest.html).

## Go: pprof

During a bounded workload, collect through the private listener/tunnel:

```bash
curl --fail --max-time 15 -o cpu.pprof 'http://127.0.0.1:6060/debug/pprof/profile?seconds=5'
go tool pprof -top -nodecount=15 ./MATCHING_BINARY cpu.pprof
go tool pprof -top -cum -nodecount=15 ./MATCHING_BINARY cpu.pprof
curl --fail --max-time 10 -o heap.pprof 'http://127.0.0.1:6060/debug/pprof/heap'
go tool pprof -top -alloc_space ./MATCHING_BINARY heap.pprof
```

Keep the matching binary and sufficient symbols. Flat cost is executing in the
function; cumulative cost includes descendants. Heap in-use and allocation totals
answer different questions. An idle/short profile with no samples is inconclusive.
Block/mutex profiles need their rates enabled in the actual app; do not claim they
were collected merely because a pprof endpoint exists. On Linux, existing perf /
flamegraph is another choice; confirm permissions and useful stacks first.

Primary source: [Go diagnostics](https://go.dev/doc/diagnostics),
[profiling Go programs](https://go.dev/blog/pprof).
