# retro log

What real targets taught the plugin, one row per resolved friction group.

| when | problem | script | message | fix |
|---|---|---|---|---|
| 2026-10-17T09:19:03Z | - | bench.sh | command failed with status 1 | bfafa6e preset parse_bench fetches result.json from the bench host when the ssh output ended before the trailing cat |
| 2026-10-17T09:19:03Z | - | bench.sh | command failed with status 1 | bfafa6e preset parse_bench fetches result.json from the bench host when the ssh output ended before the trailing cat |
| 2026-10-17T09:19:03Z | - | bench.sh | no result line in /Users/shm11c3/Develop/ISUCON/isucon13-practice/.kaizen/bench- | bfafa6e preset parse_bench fetches result.json from the bench host when the ssh output ended before the trailing cat |
| 2026-10-17T09:19:03Z | - | retro.sh | observe dump is blind to the app's queries: the Go app runs every parameterized  | bfafa6e observe.sh MYSQL_DIGEST_SOURCE=slowlog + scripts/slowlog_digest.py; performance_schema mode prints the com/Execute count |
| 2026-10-17T09:19:03Z | - | retro.sh | observe request table: nginx combined log puts the method in $6 with a leading d | bfafa6e observe.sh strips the leading quote from the nginx combined-log method |
| 2026-10-17T09:19:03Z | - | retro.sh | preset PATH_ID_REGEX '/[0-9]+|/user/[^/]+' swallowed the /user segment (GET /api | 93c9d99 presets/isucon13.sh PATH_ID_REGEX matches only the id segment |
| 2026-10-17T09:20:15Z | - | bench.sh | /Users/shm11c3/Develop/ISUCON/isucon13-practice/.kaizen/bench-baseline.json exis | a78685b bench.sh files out-of-experiment samples under baseline/<stable>/ with a timestamp |
| 2026-10-17T09:20:15Z | - | status.sh | command failed with status 141 | a78685b friction_err ignores status 141 |
