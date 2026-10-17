---
id: small-table-repeated-read
name: Master data read from the DB on every use
stage: early
cost: 10 min
risk: low
signature: a SELECT on a settings/master/model/tag table is called >=300 times returning <=1 row each
sources:
  - https://isucon.net/archives/58001272.html
---
## Symptom

Small tables that change rarely or never during the run (`settings`,
`chair_models`, `tags`, `themes`) are queried per request or per row.

## Hypothesis template

Loading the table into memory at `/initialize` (and on the write paths that
change it) and reading from the map removes the queries at zero correctness
cost.

## Change template

A package-level map loaded in `/initialize` after the data reload; reads use
the map; the rare write paths update both the table and the map.

## Checklist

- Load after `/initialize` restores the data, not before.
- If the table is written during the run (`settings.payment_gateway_url` is
  set by initialize in ISUCON14), the write must update the map.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
| isucon13 | 003-tags-in-memory | 7907/7955 | 9109 | +15% | 2+1 | 4 | promote | promote | リクエストタイムアウト:GET:/api/user/:name/iconx1,リクエストタイムアウト:GET:/api/user/:name/statisticsx3,リクエストタイムアウト:POST:/api/livestream/:id/livecommentx1,リクエストタイムアウト:POST:/api/livestream/reservationx1,一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx4; リクエストタイムアウト:POST:/api/livestream/:id/livecomment/:id/reportx1,一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/livecomment/:id/reportx1 |
