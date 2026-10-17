"""Mechanical signatures: one function per pattern id.

Each function takes the parsed observation and returns a list of evidence
strings (empty when the signature does not fire) and a strength in [0, 1]
used only to order the report. Keep every rule explainable in one sentence,
and keep that sentence in the pattern file's `signature:` line.

Observation fields (see match.py):
  digests:  list of dicts total_s, calls, avg_ms, rows_examined, rows_sent, query
  requests: list of dicts count, method, path, status
  indexes:  list of "table.index(cols)" strings
  bench_seconds: int or None
"""

from __future__ import annotations

import re

Rule = tuple[list[str], float]


def _total_db_seconds(obs) -> float:
    return sum(d["total_s"] for d in obs["digests"]) or 0.0


def _total_requests(obs) -> int:
    return sum(r["count"] for r in obs["requests"]) or 0


def _tables_with_only_primary(obs) -> set[str]:
    by_table: dict[str, set[str]] = {}
    for entry in obs["indexes"]:
        m = re.match(r"([^.]+)\.([^(]+)\(", entry)
        if m:
            by_table.setdefault(m.group(1), set()).add(m.group(2))
    return {t for t, names in by_table.items() if names == {"PRIMARY"}}


def missing_secondary_index(obs) -> Rule:
    evidence, strength = [], 0.0
    total = _total_db_seconds(obs)
    only_primary = _tables_with_only_primary(obs)
    for d in obs["digests"]:
        q = d["query"].upper()
        if not q.startswith("SELECT"):
            continue
        ratio = d["rows_examined"] / max(d["rows_sent"], 1)
        if ratio >= 50 and d["calls"] >= 20:
            evidence.append(f"{d['query'][:90]}: examined {d['rows_examined']:,} rows for {d['rows_sent']:,} sent "
                            f"({ratio:.0f}x) over {d['calls']} calls, {d['total_s']}s")
            strength = max(strength, min(1.0, d["total_s"] / total) if total else 0.5)
        for table in only_primary:
            if re.search(rf"\b{re.escape(table)}\b.*\bWHERE\b", q, re.I) and "PRIMARY" not in q:
                evidence.append(f"{table} has only PRIMARY and is filtered: {d['query'][:80]}")
                strength = max(strength, 0.4)
    return sorted(set(evidence), key=evidence.index), strength


def n_plus_one_query(obs) -> Rule:
    evidence, strength = [], 0.0
    reqs = _total_requests(obs)
    for d in obs["digests"]:
        q = d["query"].upper()
        if q.startswith("SELECT") and d["rows_sent"] <= 2 * max(d["calls"], 1) and d["calls"] >= 500 \
                and re.search(r"WHERE\s+`?\w+`?\s*=\s*\?", q) and d["avg_ms"] < 5 \
                and not re.search(r"access_token|session", q, re.I):  # that is auth-lookup-per-request
            evidence.append(f"{d['query'][:90]}: {d['calls']} calls returning {d['rows_sent']} rows total "
                            f"(avg {d['avg_ms']}ms) across {reqs or '?'} requests")
            strength = max(strength, min(1.0, d["calls"] / max(reqs, 1)))
    return evidence, strength


def fsync_on_commit(obs) -> Rule:
    total = _total_db_seconds(obs)
    for d in obs["digests"]:
        if d["query"].upper().startswith("COMMIT") and total and d["total_s"] / total >= 0.2 and d["avg_ms"] >= 2:
            share = d["total_s"] / total
            return ([f"COMMIT took {d['total_s']}s of {total:.1f}s DB time ({share:.0%}), "
                     f"{d['calls']} commits at {d['avg_ms']}ms each: waiting on fsync"], share)
    return [], 0.0


def random_order_matching(obs) -> Rule:
    for d in obs["digests"]:
        if "RAND" in d["query"].upper():
            return ([f"{d['query'][:90]}: ORDER BY RAND() over {d['calls']} calls, {d['rows_examined']:,} rows examined"],
                    0.6)
    return [], 0.0


def hot_polling_endpoint(obs) -> Rule:
    reqs = _total_requests(obs)
    evidence, strength = [], 0.0
    for r in obs["requests"]:
        share = r["count"] / reqs if reqs else 0
        if r["method"] == "GET" and share >= 0.25:
            evidence.append(f"{r['method']} {r['path']} {r['status']}: {r['count']} requests ({share:.0%} of all)")
            strength = max(strength, share)
    return evidence, strength


def heavy_aggregate_query(obs) -> Rule:
    evidence, strength = [], 0.0
    total = _total_db_seconds(obs)
    for d in obs["digests"]:
        q = d["query"].upper()
        if q.startswith("SELECT") and re.search(r"\b(SUM|COUNT|AVG|GROUP BY|ORDER BY .* LIMIT)\b", q) and d["avg_ms"] >= 10:
            evidence.append(f"{d['query'][:90]}: avg {d['avg_ms']}ms x {d['calls']} calls = {d['total_s']}s")
            strength = max(strength, min(1.0, d["total_s"] / total) if total else 0.3)
    return evidence, strength


def single_row_insert_loop(obs) -> Rule:
    evidence, strength = [], 0.0
    for d in obs["digests"]:
        q = d["query"].upper()
        if q.startswith("INSERT") and d["calls"] >= 1000 and "..." not in d["query"]:
            evidence.append(f"{d['query'][:90]}: {d['calls']} single-row inserts, {d['total_s']}s")
            strength = max(strength, 0.4)
    return evidence, strength


def auth_lookup_per_request(obs) -> Rule:
    reqs = _total_requests(obs)
    evidence, strength = [], 0.0
    for d in obs["digests"]:
        if re.search(r"access_token|session_id|token\s*=", d["query"], re.I) and d["calls"] >= 0.15 * max(reqs, 1) and reqs:
            evidence.append(f"{d['query'][:90]}: {d['calls']} calls for {reqs} requests")
            strength = max(strength, min(1.0, d["calls"] / reqs))
    return evidence, strength


def small_table_repeated_read(obs) -> Rule:
    evidence, strength = [], 0.0
    for d in obs["digests"]:
        q = d["query"].upper()
        if q.startswith("SELECT") and d["calls"] >= 300 and d["rows_sent"] <= d["calls"] \
                and re.search(r"\bFROM\s+`?(settings|configs?|.*_models?|.*masters?|tags|themes|categories)`?\b", q, re.I):
            evidence.append(f"{d['query'][:90]}: {d['calls']} reads of a small, rarely changing table")
            strength = max(strength, 0.3)
    return evidence, strength


def db_busy_separate_host(obs) -> Rule:
    total = _total_db_seconds(obs)
    secs = obs.get("bench_seconds") or 60
    if total >= 0.6 * secs:
        return ([f"DB statements took {total:.0f}s during a {secs}s run: the database is a core-bound host"],
                min(1.0, total / secs / 2))
    return [], 0.0


def static_assets_via_app(obs) -> Rule:
    reqs = _total_requests(obs)
    hits = [r for r in obs["requests"]
            if re.search(r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff2?)$|^/(assets|static|images|img)/", r["path"])]
    count = sum(r["count"] for r in hits)
    if reqs and count / reqs >= 0.1:
        return ([f"{count} static-asset requests ({count / reqs:.0%} of all); serve from nginx with cache headers"],
                count / reqs)
    return [], 0.0


RULES = {
    "missing-secondary-index": missing_secondary_index,
    "n-plus-one-query": n_plus_one_query,
    "fsync-on-commit": fsync_on_commit,
    "random-order-matching": random_order_matching,
    "hot-polling-endpoint": hot_polling_endpoint,
    "heavy-aggregate-query": heavy_aggregate_query,
    "single-row-insert-loop": single_row_insert_loop,
    "auth-lookup-per-request": auth_lookup_per_request,
    "small-table-repeated-read": small_table_repeated_read,
    "db-busy-separate-host": db_busy_separate_host,
    "static-assets-via-app": static_assets_via_app,
}
