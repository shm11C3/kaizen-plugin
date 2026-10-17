---
id: dns-water-torture
name: Authoritative DNS backed by the application DB under random-subdomain load
stage: mid
cost: 30-60 min
risk: mid
signature: none from the app dump (needs the DNS server's query log or MySQL digests on the PowerDNS schema)
sources:
  - https://isucon.net/archives/58001272.html (ISUCON13 解説: DNS 水責め、TTL、PowerDNS キャッシュ、dnsdist)
---
## Symptom

ISUCON13 only, so far: the benchmarker resolves names through PowerDNS
whose MySQL backend shares the host (indexes removed); random subdomains
defeat caching and load MySQL.

## Hypothesis template

Raising the TTL (initially 0) so the benchmarker caches, enabling PowerDNS
caching, restoring the backend indexes, and moving DNS (and its DB) to
another host removes DNS load from the application database.

## Change template

In order: TTL; PowerDNS cache settings; indexes on the PowerDNS schema;
separate host; dnsdist filter delaying or dropping NXDOMAIN; a wildcard
record (`*.u.isucon.dev`) to skip per-user inserts, with the HTTP side
effects the 解説 warns about.

## Checklist

- The benchmarker rate-limits DNS; the sponsor award counted successful
  resolutions, so dropping answers has a cost.
- Wildcard makes torture queries succeed and increases scraping-like HTTP
  traffic; handle that too.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

## Notes from write-ups

- Kept for the "new infrastructure component" case: a future contest may
  plant a component outside the app the same way.
