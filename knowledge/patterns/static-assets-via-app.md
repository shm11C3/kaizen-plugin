---
id: static-assets-via-app
name: Static files and immutable blobs served through the application
stage: early
cost: 10-20 min
risk: mid
signature: >=10% of requests target asset paths (js/css/images/icons)
sources:
  - https://isucon.net/archives/58001272.html
  - https://hackmd.io/@usatie/SyhUqFf39
---
## Symptom

Images or assets go through the application (and sometimes the DB: ISUCON13
icons stored as BLOBs, SHA-256 computed per request). The access log shows
asset paths with high counts and the app spends CPU on bytes it never
changes.

## Hypothesis template

Serving the files from nginx (`try_files`, `expires`) or answering `304 Not
Modified` when `If-None-Match` matches a stored hash removes the
application from the asset path.

## Change template

- Cheapest when one app process serves everything: hash kept in memory per
  owner (filled on upload or first read), `304` when `If-None-Match` names
  it, the same hash for the response field; no schema change.
- nginx `location` for the asset prefix with `expires` and `gzip_static`.
- For user-uploaded images: write the file to disk on upload, serve via
  nginx, keep the hash in a column (`icon_hash`) filled on write, return
  it as ETag, answer 304 on match.

## Checklist

- The hash must reflect an update within the manual's freshness window;
  parse `If-None-Match` properly (lists, weak validators), not by substring.
- Moving uploads to disk can slow the write path; measure, do not assume.
- The restart test: files written to disk must survive, and `/initialize`
  must restore the initial set.
- Before building the 304 path, confirm the client sends the validator:
  tcpdump on the app port during a run (isucon13: most icon GETs carried
  `If-None-Match: "<sha256>"`, and the same hash is the `icon_hash` field
  of every user response, so one in-memory map serves both).
- An in-memory hash map needs: clear on `/initialize`, drop before the
  upload's DELETE/INSERT and set after its COMMIT, and a miss that never
  overwrites a value an upload stored meanwhile (isucon13/002).

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon13 | 002-icon-etag-304 | 5077/6635/6815 | 7907/7955 | +20% | 3+2 | 3 | promote | promote | 一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx1; 一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx2 |
