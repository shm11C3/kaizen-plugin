---
id: dns-water-torture
name: Authoritative DNS backed by the application DB under random-subdomain load
stage: mid
cost: 30-60 min
risk: mid
signature: none from the app dump (needs the DNS server's query log or MySQL digests on the PowerDNS schema)
sources:
  - https://isucon.net/archives/58001272.html
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
record to skip per-user inserts, accepting that torture queries then
resolve and turn into HTTP traffic.

## Checklist

- Check the manual for how DNS answers are scored before dropping or
  delaying them.
- Wildcard makes torture queries succeed and increases scraping-like HTTP
  traffic; handle that too.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

