---
id: hot-polling-endpoint
name: One polled GET dominates the request mix
stage: early
cost: 5-15 min
risk: mid
signature: a single GET path is >=25% of all requests
sources:
  - https://isucon.net/archives/58869617.html
  - https://zenn.dev/layerx/articles/3bd55b77e047c4
---
## Symptom

`GET /api/chair/notification` and `GET /api/app/notification` are polled
every 30ms per client; they are 80% of requests and each hits the DB. The
endpoint's own cost matters less than its count.

## Hypothesis template

The client honours `retry_after_ms`; raising it from 30 to N ms cuts the
notification requests by 30/N with no code change, freeing the DB for
work that scores. Too large a value delays state changes the client must
see and lowers satisfaction: tune by measurement, do not maximise.

## Change template

1. Return a larger `retry_after_ms` (100 → 300 → 1000, measuring each).
2. Serve the polled answer from memory: cache the latest ride status per
   chair/user, invalidate on status change (one map, one mutex).
3. SSE only when the above are exhausted; it needs push on status change
   (channel/pub-sub) to pay off; budget it as a late, risky experiment.

## Checklist

- Manual: polling intervals are usually a documented knob; check
  `.kaizen/RULES.md` before changing them.
- A cached answer must reflect a status change within the grace the
  manual gives; read the manual's tick and timeout values first.
- Each step is its own experiment: the interval change and the cache are
  different mechanisms.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Observed

- ISUCON14 practice observation (initial Go, 60s): 9,595 chair notifications
  and 1,622 app notifications of ~11,900 requests.
