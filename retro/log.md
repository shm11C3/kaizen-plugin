# retro log

What real targets taught the plugin, one row per resolved friction group.

| when | problem | script | message | fix |
|---|---|---|---|---|
| 2026-10-17T08:55:13Z | - | retro.sh | missed signal: hot-polling-endpoint did not fire on the real dump because nginx  | d563406 |
| 2026-10-17T08:56:14Z | - | retro.sh | defect: overlay change list empty on real host (rsync itemizes sent files as <f) | 2aaf1af |
| 2026-10-17T08:59:31Z | - | experiment.sh | commit or discard the working tree changes before closing the experiment | 1721267 |
| 2026-10-17T09:03:23Z | - | experiment.sh | command failed with status 1 | 5742a45 |
| 2026-10-17T09:03:23Z | - | retro.sh | defect: tracked .kaizen records blocked git switch main at record | 5742a45 |
| 2026-10-17T09:08:08Z | - | status.sh | command failed with status 141 | 521751d |
| 2026-10-17T09:12:52Z | - | experiment.sh | no decision.json; run evaluate.sh first (even to record an override) | guard correct: record needs evaluate first; the chain stopped at pass=false by design |
| 2026-10-17T09:20:51Z | - | deploy.sh | command failed with status 125 | 51a4f09 preset: build as isucon (compose plugin not installed for root) |
| 2026-10-17T09:20:51Z | - | observe.sh | OBSERVE_RESET_CMD failed on isu12: sudo truncate -s0 "$(sudo docker inspect --fo | ccffde7 preset: DOCKER_API_VERSION=1.41 pinned (docker CLI upgraded under the old daemon) |
| 2026-10-17T09:20:51Z | - | observe.sh | command failed with status 1 | ccffde7 preset: DOCKER_API_VERSION=1.41 pinned (docker CLI upgraded under the old daemon) |
| 2026-10-17T09:20:51Z | - | experiment.sh | commit or discard the working tree changes before closing the experiment | e228118 lib.sh git_dirty ignores .kaizen; 404e6eb deploy.sh refuses candidates carrying records |
| 2026-10-17T09:20:51Z | - | experiment.sh | command failed with status 1 | e228118 lib.sh git_dirty ignores .kaizen; 404e6eb deploy.sh refuses candidates carrying records |
| 2026-10-17T09:20:51Z | - | retro.sh | experiment skill: git add -A on the candidate branch swept manifest.json and tim | e228118 lib.sh git_dirty ignores .kaizen; 404e6eb deploy.sh refuses candidates carrying records |
| 2026-10-17T09:20:51Z | - | retro.sh | setup skill: committing .kaizen on main moved main past STABLE_REV; experiment.s | 51a4f09 stable.sh repin + setup/experiment skills; 364208e gitignore baseline/ and timeline |
| 2026-10-17T09:20:51Z | - | retro.sh | observe skill: performance_schema digests are blind to this app's prepared state | 74511a7 match.py names the blind digest; e228118 observe.sh dumps MySQL time by event name |
| 2026-10-17T09:20:51Z | - | retro.sh | hosts: unattended-upgrades ran for 25 min after first boot at half a core and re | 74511a7 BENCH_PRECHECK_CMD in bench.sh and preset; stable.sh forget-baseline |
| 2026-10-17T09:19:03Z | - | bench.sh | command failed with status 1 | bfafa6e preset parse_bench fetches result.json from the bench host when the ssh output ended before the trailing cat |
| 2026-10-17T09:19:03Z | - | bench.sh | no result line in /Users/shm11c3/Develop/ISUCON/isucon13-practice/.kaizen/bench- | bfafa6e preset parse_bench fetches result.json from the bench host when the ssh output ended before the trailing cat |
| 2026-10-17T09:19:03Z | - | retro.sh | observe dump is blind to the app's queries: the Go app runs every parameterized  | bfafa6e observe.sh MYSQL_DIGEST_SOURCE=slowlog + scripts/slowlog_digest.py; performance_schema mode prints the com/Execute count |
| 2026-10-17T09:19:03Z | - | retro.sh | observe request table: nginx combined log puts the method in $6 with a leading d | bfafa6e observe.sh strips the leading quote from the nginx combined-log method |
| 2026-10-17T09:19:03Z | - | retro.sh | preset PATH_ID_REGEX '/[0-9]+|/user/[^/]+' swallowed the /user segment (GET /api | 93c9d99 presets/isucon13.sh PATH_ID_REGEX matches only the id segment |
| 2026-10-17T09:20:15Z | - | bench.sh | /Users/shm11c3/Develop/ISUCON/isucon13-practice/.kaizen/bench-baseline.json exis | a78685b bench.sh files out-of-experiment samples under baseline/<stable>/ with a timestamp |
| 2026-10-17T09:20:15Z | - | status.sh | command failed with status 141 | a78685b friction_err ignores status 141 |
| 2026-10-17T09:23:54Z | - | retro.sh | a baseline sample taken under the slow log (long_query_time=0) scored 5077 vs 66 | 39506b0 samples taken while OBSERVE_SLOWLOG=1 carry observed:true and evaluate.sh ignores them (the 5077 sample predates the flag and stays in the files) |
| 2026-10-17T10:16:57Z | isucon12-qualify | bench.sh | isu12 is not ready for a sample (BENCH_PRECHECK_CMD failed: ! pgrep -f "/usr/bin | 4457e03 |
| 2026-10-17T10:16:57Z | isucon12-qualify | bench.sh | isu12 is not ready for a sample (BENCH_PRECHECK_CMD failed: ! pgrep -f "/usr/bin | 4457e03 |
| 2026-10-17T10:16:57Z | isucon12-qualify | deploy.sh | command failed with status 17 | project fix: go/Dockerfile builds from archive.debian.org with Debian's mysql client (bullseye left deb.debian.org, Oracle apt key changed); isucon12-practice de4926c |
