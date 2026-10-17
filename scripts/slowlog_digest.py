#!/usr/bin/env python3
"""slowlog_digest.py <mysql-slow.log> [limit]

Aggregate a MySQL slow query log (written with long_query_time=0) into the
same table observe.sh prints from performance_schema: total_s, calls,
avg_ms, rows_examined, rows_sent, query. The slow log sees every
statement, including server-side prepared statements, which MySQL 8.0
counts only as statement/com/Execute with no digest. Literals are
normalized to ? the way performance_schema digests do, so the matcher's
signatures apply unchanged. Runs on the DB host, so stdlib only.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict

STR = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
NUM = re.compile(r"(?<![\w`])-?\d+(?:\.\d+)?(?![\w`])")
TUPLE = re.compile(r"\(\s*\?(?:\s*,\s*\?)*\s*\)")
TUPLES = re.compile(r"\(\.\.\.\)(?:\s*,\s*\(\.\.\.\))+")
INLIST = re.compile(r"\(\s*(?:\?\s*,\s*)+\?\s*\)")
WS = re.compile(r"\s+")
META = re.compile(r"^# Query_time: ([\d.]+)\s+Lock_time: [\d.]+\s+Rows_sent: (\d+)\s+Rows_examined: (\d+)")
SKIP = re.compile(r"^(SET timestamp=|use |USE |SET @@|SET NAMES|SET SESSION|SELECT @@)", re.I)


def normalize(sql: str) -> str:
    sql = STR.sub("?", sql)
    sql = NUM.sub("?", sql)
    sql = TUPLE.sub("(...)", sql)
    sql = TUPLES.sub("(...) /* , ... */", sql)
    sql = INLIST.sub("(...)", sql)
    sql = WS.sub(" ", sql).strip().rstrip(";")
    return sql


def aggregate(path: str) -> dict[str, list[float]]:
    stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0, 0, 0])
    meta: tuple[float, int, int] | None = None
    buf: list[str] = []

    def flush() -> None:
        if meta is None:
            return
        # The statement follows its header; "SET timestamp=...;" and "use db;"
        # lines that mysqld prepends are dropped, the rest joined.
        lines = [l for l in buf if not SKIP.match(l)]
        sql = " ".join(lines)
        key = normalize(sql)
        if not key:
            return
        s = stats[key]
        s[0] += meta[0]
        s[1] += 1
        s[2] += meta[2]
        s[3] += meta[1]

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("# Query_time:"):
                flush()
                buf = []
                m = META.match(line)
                meta = (float(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
                continue
            if line.startswith("#") or not line.strip():
                continue
            buf.append(line)
        flush()
    return stats


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    stats = aggregate(sys.argv[1])
    print("total_s\tcalls\tavg_ms\trows_examined\trows_sent\tquery")
    for q, (total, calls, examined, sent) in sorted(stats.items(), key=lambda kv: -kv[1][0])[:limit]:
        print(f"{total:.2f}\t{calls}\t{total / calls * 1000:.2f}\t{examined}\t{sent}\t{q[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
