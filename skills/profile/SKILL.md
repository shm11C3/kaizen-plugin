---
name: profile
description: "Explain a measured ISUCON bottleneck with existing profilers, access/SQL analysis or bounded OpenTelemetry HTTP-to-DB tracing. Use when an observation needs causal detail before choosing an optimization; produce evidence and a testable hypothesis."
---

# Profile a measured cost

Set `K` to this skill's base directory `/../..`. Read the current observation,
candidate/source SHA and remaining time. Choose a question that changes the next
implementation decision. Use [observe](../observe/SKILL.md) for the owned target
and benchmark lifecycle. A local workload is diagnostic evidence, not an official
score or checker result.

## Choose the next measurement

| Uncertainty | Start with | Inspect |
|---|---|---|
| Which route consumes total request time? | Existing timed access log + alp | count, sum, avg, errors; normalize route IDs |
| CPU or allocation cost within the process? | Go pprof; Rust's existing profiler | application stacks, flat vs cumulative, sample volume |
| Many DB calls or a costly query? | slowlog / performance_schema + pt-query-digest / EXPLAIN | calls, total time, rows examined, existing indexes |
| Which HTTP operation owns DB/downstream waits? | OTel HTTP and matching DB instrumentation | context propagation, parent/child links, observed intervals |

Reuse installed tools and compatible dependencies. Check their version and one
real output before analysis. Choose one or two complementary signals; stop once
the uncertainty is resolved. A missing timer, empty profile or absent DB span
is missing evidence. It does not mean zero cost. Read [tool recipes](references/tools.md)
only for the selected measurement. Use [Go](../../templates/go-observation/README.md)
or [Rust](references/rust.md) only when instrumentation is needed.

## Collect a bounded window

- Keep the deployable source, dependency versions, build mode, target identity,
  sampling rate and workload with the artifact. Instrumentation is a normal
  candidate with a way to restore the normal build. Run existing tests and lint
  suites; adjust expensive checks from their measured cost.
- In a team, only the reservation owner deploys and starts/stops target collection
  through `target.py`. Set the preset's `OBSERVE_START_CMD`, `OBSERVE_STOP_CMD`
  and `OBSERVE_TOOLS` to the actual activation and verified deactivation commands.
  Use `observe start NAME` → a bounded workload / allowed benchmark → dump →
  `observe stop`. The existing marker keeps instrumented samples out of adoption.
  After a failed start/stop, retain the marker and repair the stop operation.
- OTel requires both a server span and DB/client instrumentation that receives
  that request context. Wrap the library actually in use; don't replace the
  database driver or application behavior to fabricate a trace. Capture a known
  request and prove its DB spans share the trace and have connected parents.
- Keep operation/route labels static and low-cardinality. Do not export SQL text,
  arguments, credentials, cookies, bodies, raw IDs or error messages containing
  inputs. Local private JSON export is enough for a short diagnosis. Reuse an
  allowed existing Collector/backend when it improves inspection; don't build a
  new observability platform before learning from the first trace.
- Measure output size and collection cost. Use a small sample for diagnosis,
  flush on graceful shutdown and verify nonempty output. Remove/disable collection
  and verify the actual exporter/listener stopped before normal score samples.
  The Go flag is read at startup, so deleting it alone does not disable a running process.

## Turn the evidence into a candidate

For the Go JSON export, retain the raw artifact and run:

```bash
python3 "$K/scripts/trace_summary.py" TRACE.json \
  --observation OBSERVATION_REF --output SUMMARY.json \
  --allow-route '/static/route/{id}'
```

Declare only static route patterns. The summary redacts unapproved names and
attributes; it does not make the original file safe to publish. Treat malformed
or truncated input as failed collection. Other export formats need their own
validated reader; don't rename an OTLP/Rust file to imply this reader supports it.

Read the source-bound report and answer:

1. Which route/operation dominates, by how much, and under which workload?
2. Does evidence point to CPU, allocation, DB round-trip count, query work or
   another wait? Match trace ownership to SQL fingerprints or profile stacks.
3. What change follows, and which next measurement would disprove it?

Nested and parallel spans overlap. Use the union of observed DB intervals within
the HTTP span for observed DB wall time; their duration sum is work, not elapsed
request time. Time outside those intervals is unclassified, not automatically
CPU time. Sampling/orphans/missing instrumentation limit coverage. Distinguish
association from causality and verify the proposed change with the real benchmark.

Give [hypothesize](../hypothesize/SKILL.md) the raw/derived paths, source SHA,
tool versions, costs, limitations and one falsifiable mechanism. In practice,
problem-specific SQL and discoveries belong in knowledge; improve this reusable
skill through [improve-workflow](../improve-workflow/SKILL.md). Existing quality
holds, reservation and recovery rules remain in force.
