---
id: external-service-idempotency
name: Retrying an external call through a slow verification path
stage: late
cost: 15 min
risk: low
signature: none (benchmark errors or code review: retries that call a status/verify API)
sources:
  - https://isucon.net/archives/58869617.html
---
## Symptom

A payment or external request sometimes returns an error even though it
succeeded; the reference code retries by first calling a slow verification
API. Latency on the ride-completion path grows with retries.

## Hypothesis template

Sending an `Idempotency-Key` (e.g. the ride id) lets the gateway deduplicate
retries, so the client can resend without the verification call.

## Change template

Set the header on the request; on error, retry the same request with the
same key; drop the verification call.

## Checklist

- The key must be unique per logical payment (ride id), stable across
  retries.
- Often a small win: measure before spending time beyond the header.

## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|

