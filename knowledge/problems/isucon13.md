# isucon13 (ISUPipe)

References (read, not reproduced): https://isucon.net/archives/58001272.html

Observed on the reference Go implementation (our own dumps): every table
except users/tags has only PRIMARY; the Go app runs its queries as
server-side prepared statements, so performance_schema digests miss them
(use MYSQL_DIGEST_SOURCE=slowlog); the benchmarker sends If-None-Match with
the icon's sha256 on most `GET /api/user/:name/icon` calls (46% of all
requests); `GET /api/user/:name/statistics` times out (499) on the reference
code because it runs two aggregate queries per user for the ranking.

Patterns worth checking on this problem, from reading the references:
missing-secondary-index, static-assets-via-app (icons, conditional GET),
n-plus-one-query, heavy-aggregate-query (statistics), dns-water-torture,
db-busy-separate-host. The score counts tips, not requests: check the
manual for what reaches the tip scenarios before optimising a path.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
| 001-add-secondary-indexes | missing-secondary-index | +80% | promote | 13 secondary indexes created from initialize; median 3733 -> 6725 (+80%), both candidate samples above every baseline sample |
| 002-icon-etag-304 | static-assets-via-app | +20% | promote | icon hash cached in memory, 304 on If-None-Match: median 6725 -> 7931 (+18%); the 5077 baseline sample was taken under the slow log before the observed flag existed |
| 003-tags-in-memory | small-table-repeated-read | +15% | promote | rule decision as evaluated (taken over from the subagent) |
