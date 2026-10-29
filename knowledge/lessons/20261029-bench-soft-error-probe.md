# Explain an unexplained benchmark soft error with an instrumented benchmark

- Mode: practice (ISUCON14 R3). Applies whenever the benchmark source is published.
- Evidence: practice fork `iikanjini-kaizen-agent/isucon-competition-practice-20261029-r3`,
  stable `e79558743f1222241d7eabce31bf3cfaea08142a`, task T-0044.

## What happened

Code 31 (fewer nearby chairs than expected) rose with every throughput gain
(T39 140, T42 232) and failed T42 at the benchmark's error limit (200 soft errors
in total). DB measurements during runs ruled out notification and accept latency,
yet four hypotheses about the cause had been tested and rejected over several hours.

One run of a copy of the benchmark, with a log line added where it counts the
error, settled it in 15 minutes: 72 of 76 in-run errors were chairs with no ride
history, 0-300 ms after activation. The benchmark treats a new chair as waiting
from the moment activation returns, while the app showed it only after its
position buffer (50 ms) and nearby-chairs cache (200 ms) had both refreshed.

## How to apply

- When a soft error code persists after two measured hypotheses, stop guessing:
  read the benchmark's check, add one log line with the inputs of its decision,
  build it (`GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w'`), and
  run it once against stable under an environment reservation while the
  integrator is idle. Keep the official binary untouched; use `run -s` if the
  static-file check differs by version.
- Count only log lines from before the load ended: the benchmark discards checks
  that complete after `finished`, an instrumented copy does not.
- Without SSH to the benchmark host, xz the binary and send it through SSM in
  46 KB base64 chunks in parallel (5.5 MB took about one minute), verify sha256,
  then copy it from the control host.
- Practice only. In a contest the benchmark is not available locally; there the
  equivalent is reading the published checker and testing the app-side window.
