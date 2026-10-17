# isucon13 (ISUPipe)

Official 解説: https://isucon.net/archives/58001272.html. Score = total tips,
not request count, so request optimisations pay only where they reach the
tip scenarios.

| order | what | pattern | numbers from sources |
|---|---|---|---|
| 1 | indexes (livestream_tags, icons/themes/livestreams.user_id, livecomments.livestream_id, reactions(livestream_id, created_at), ...) | missing-secondary-index | ≈3,000 → ≈10,000 |
| 2 | icon SHA-256 per request → `icon_hash` column, 304 on `If-None-Match` | static-assets-via-app | icon update must show within 2s |
| 3 | `fill*Response` N+1 (5 functions) | n-plus-one-query | JOIN / preload / cache |
| 4 | user and livestream statistics N+1 | heavy-aggregate-query | one query or a results table |
| 5 | NG-word registration scanning past comments | (no pattern yet) | — |
| 6 | PowerDNS water torture: TTL, cache, indexes, separate host, dnsdist | dns-water-torture | benchmarker rate-limits DNS |

Host layouts from the 解説: heavy DNS → [DNS + DNS DB] / [nginx + app] /
[app DB]; after DNS fixes → [nginx + DNS + DNS DB] / [app] / [app DB].

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
