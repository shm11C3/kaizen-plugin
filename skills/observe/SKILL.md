---
name: observe
description: Collect the evidence a hypothesis must cite. Use before every hypothesis and after every promotion: resets the counters, runs or records one benchmark, dumps MySQL digests, request mix, and indexes into observe-<name>.txt, and summarizes the top three costs.
---

# Observe

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run from
the repository root.

```bash
$K/scripts/status.sh                      # stable, deployed, open experiment, budget
$K/scripts/observe.sh reset               # clear performance_schema digests and the access log
$K/scripts/bench.sh <label>               # ssh mode; manual mode: --result '...' after the portal run
$K/scripts/observe.sh dump <name>         # writes observe-<name>.txt, prints its path
```

Label rules: `baseline`, `baseline-2`, ... when the stable revision is
deployed; `candidate`, `candidate-2`, ... inside an open experiment with the
candidate deployed. The script refuses anything else.

Read the dump and answer, in a few lines, with numbers from the file:

1. Which three statements take the most total time, and are they slow per
   call (avg_ms) or just frequent (calls)? High `rows_examined` with low
   `rows_sent` means a missing index.
2. Which three request paths dominate the count, and which return errors?
3. What is already indexed, so the next hypothesis does not repeat exp
   records in `.kaizen/log.md`.

When the digest table shows only COMMIT, the initialize INSERTs and a
handful of SELECTs while the request table shows thousands of API calls,
the app is running its queries as server-side prepared statements, which
performance_schema does not digest (the dump prints the
statement/com/Execute count as a hint). Set `MYSQL_DIGEST_SOURCE=slowlog`
in the preset: reset turns the slow log on at `long_query_time=0`, dump
aggregates it (`scripts/slowlog_digest.py`) and turns it off. Logging every
statement costs score (about a quarter on isucon13 once the scans were
gone), so the sample taken between reset and dump is marked `observed`
and evaluate.sh leaves it out; it still needs a passing run. Take the
samples the rule uses after the dump.

When the dump is thin, extend it instead of guessing: `OBSERVE_EXTRA_CMD`
in config.sh runs one more command on the nginx host (alp with a route
pattern, pprof, slow log) and appends its output to the dump. Observation
files are evidence; never edit them.

Hand the file path and the three answers to the hypothesize skill.
