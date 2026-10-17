# isucon13 (ISUPipe)

References (read, not reproduced): https://isucon.net/archives/58001272.html

Patterns worth checking on this problem, from reading the references:
missing-secondary-index, static-assets-via-app (icons, conditional GET),
n-plus-one-query, heavy-aggregate-query (statistics), dns-water-torture,
db-busy-separate-host. The score counts tips, not requests: check the
manual for what reaches the tip scenarios before optimising a path.

Experiments in the order they were run.

| experiment | pattern | delta | final | reason |
|---|---|---|---|---|
