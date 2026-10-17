---
name: observe
description: Collect the evidence a hypothesis must cite. Use before every hypothesis and after every promotion: resets the counters, runs or records one benchmark, dumps MySQL digests, request mix, and indexes into observe-<name>.txt, and summarizes the top three costs.
---

# Observe

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup).

```bash
$K/scripts/status.sh                      # stable, deployed, open experiment, budget
$K/scripts/observe.sh reset               # clear performance_schema digests and the access log
$K/scripts/bench.sh <label>               # ssh mode; manual mode: --result '...' after the portal run
$K/scripts/observe.sh dump <name>         # writes observe-<name>.txt, prints its path
```

Label rules: `baseline`, `baseline-2`, ... when the stable revision is
deployed; `candidate`, `candidate-2`, ... inside an open experiment with the
candidate deployed. The script refuses anything else, and refuses any
sample while `BENCH_PRECHECK_CMD` (config.sh) fails on a host: a host busy
with something that is not the application (a package upgrade, a leftover
process) produces noise, not a sample. When samples turn out to have been
taken on a busy host, `$K/scripts/stable.sh forget-baseline <reason>`
retires them (kept as evidence, out of the evaluation) and a new baseline
is taken.

Read the dump and answer, in a few lines, with numbers from the file:

1. Which three statements take the most total time, and are they slow per
   call (avg_ms) or just frequent (calls)? High `rows_examined` with low
   `rows_sent` means a missing index.
2. Which three request paths dominate the count, and which return errors?
3. What is already indexed, so the next hypothesis does not repeat exp
   records in `.kaizen/log.md`.

When the dump is thin, extend it instead of guessing: `OBSERVE_EXTRA_CMD`
in config.sh runs one more command on the nginx host (alp with a route
pattern, pprof, slow log) and appends its output to the dump. Observation
files are evidence; never edit them.

Hand the file path and the three answers to the hypothesize skill.
