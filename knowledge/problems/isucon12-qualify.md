# isucon12-qualify (ISUPORTS)

References (read, not reproduced): https://isucon.net/archives/56850281.html

Patterns worth checking on this problem, from reading the references:
initialize-reset-and-data-shrink (per-tenant SQLite, large initial data,
initialize time limit), missing-secondary-index, single-row-insert-loop,
response-cache-with-invalidation, heavy-aggregate-query (billing),
n-plus-one-query, prefork-worker-count. Not yet in the catalog: a coarse
file lock around reads, id generation through an auto_increment table,
backpressure with 429; write them as new patterns when measured.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
