---
id: static-assets-via-app
name: Static files and immutable blobs served through the application
stage: early
cost: 10-20 min
risk: mid
signature: >=10% of requests target asset paths (js/css/images/icons)
sources:
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: icon_hash、If-None-Match で 304)
  - https://hackmd.io/@usatie/SyhUqFf39 (ISUCON13 write-up: nginx 配信でスコアが下がった例)
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

- nginx `location` for the asset prefix with `expires` and `gzip_static`.
- For user-uploaded images: write the file to disk on upload, serve via
  nginx, keep the hash in a column (`icon_hash`) filled on write, return
  it as ETag, answer 304 on match.

## Checklist

- ISUCON13 解説: the hash must reflect an icon update within 2 seconds; the
  sample's substring match on `If-None-Match` is wrong for lists/weak
  validators.
- A write-up reports a score drop after moving icons to nginx (writes got
  slower); measure, do not assume.
- The restart test: files written to disk must survive, and `/initialize`
  must restore the initial set.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- Not present in ISUCON14 (no user images); the signature stays quiet there.
