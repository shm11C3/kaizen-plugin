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
3. Check SSE support in the rules and both clients early. When polling or
   state-transition delay dominates, compare bounded SSE/difference notifications
   by expected gain and total time; do not reserve it automatically for late work.
   A stream needs a cheaper update path to pay off, not the same expensive query
   loop at a higher frequency.

## Checklist

- Manual: polling intervals are usually a documented knob; check
  `.kaizen/RULES.md` before changing them.
- A cached answer must reflect a status change within the grace the
  manual gives; read the manual's tick and timeout values first.
- Each step is its own experiment: the interval change and the cache are
  different mechanisms.
- Read existing benchmark satisfaction/transition metrics as well as request
  counts. Preserve order, reconnect behavior and cross-app visibility; process-local
  caches alone cannot observe another app's writes. See the
  [R2 practice lesson](../lessons/20261029-isucon14-r2-feedback.md).

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon14 | 002-notification-interval | 2519/2527/2900 | 3627/4119 | +53% | 3+2 | 2 | promote | promote | map[25:12]; map[25:19] |

## Observed

- ISUCON14 practice observation (initial Go, 60s): 9,595 chair notifications
  and 1,622 app notifications of ~11,900 requests.
