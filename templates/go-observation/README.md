# Go observation candidate

Copy `observe.go` into an isolated `package main` observation candidate and wrap
its handler with `kaizenObserve(handler)`. Resolve compatible official OTel modules
in that application's go.mod/go.sum; the example was compiled and exercised with
Go1.24.4 and OTel/stdouttrace/sdk1.31.0. Preserve the lockfiles in the candidate.

The private flag is read once on process startup. Configure OBSERVE_START_CMD to
create it and restart the observation app, and OBSERVE_STOP_CMD to remove it,
restart, and verify the private profile listener is gone. Use the team target
wrapper for observe start/stop and all deployments. Default paths:

- `/var/tmp/kaizen-observation-enabled`
- `/var/tmp/kaizen-observation-traces.jsonl` (0600, static method-only HTTP spans)
- `127.0.0.1:6060/debug/pprof/` (private listener, separate ServeMux)

Environment overrides: KAIZEN_OBSERVE_FLAG and KAIZEN_TRACE_FILE. Sampling is1%.
Synchronous sampled file export adds work, so active sessions are observation only.
No flag means the original handler is returned without SDK/listener initialization.
A file/listener failure logs an error; verify actual nonempty trace/profile output.
There is no SQL auto-instrumentation, collector or viewing backend in this example.
Never publish the diagnostic listener through the public application router.
For final performance, prefer deploying a normal candidate without this dependency
when instrumentation is no longer needed, then verify/rebaseline normally.
