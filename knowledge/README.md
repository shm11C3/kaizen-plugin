# knowledge

Measured ISUCON improvement patterns. The corpus answers, from evidence
rather than folklore, three questions the hypothesize step needs:

1. **Which pattern does this observation show?** `match.py` reads an
   `observe-*.txt` dump and lists the patterns whose mechanical signature
   fires, with the evidence lines.
2. **What is done about it?** Each `patterns/<id>.md` carries the hypothesis
   and change templates and the checklist of what tends to break.
3. **What did it pay, and how often did it fail?** The `## Measured` table
   in each pattern file is appended automatically by `scripts/knowledge.sh
   ingest` from every closed experiment's `record.json`.

Internet write-ups and the official 解説 seed the pattern files (see each
file's `sources:`); only the Measured tables count as evidence. A pattern
with no measured row is a hypothesis about the pattern, not knowledge.

## Layout

```
patterns/<id>.md      one pattern: signature, templates, checklist, measured rows, sources
signatures.py         the mechanical signature rules, one function per pattern id
match.py              observe dump -> ranked patterns with evidence (uses signatures.py)
records/<problem>/    record.json of every ingested experiment, verbatim
problems/<problem>.md what was found on that problem, in the order it was found
```

## Pattern file contract

Frontmatter between `---` lines, then fixed headings. Humans and the agent
read the whole file; `knowledge.sh` only parses the frontmatter and appends
rows under `## Measured`.

```
---
id: missing-secondary-index
name: Missing secondary index on hot lookups
stage: early        # early | mid | late: when in an 8h contest it usually pays
cost: 5-15 min      # typical wall time for one experiment
risk: low           # low | mid | high: how often it breaks correctness
signature: SELECT digests examining >=50x the rows they return; tables with only PRIMARY
sources:
  - https://isucon.net/archives/58869617.html
---
## Symptom
## Hypothesis template
## Change template
## Checklist
## Measured
| problem | experiment | baseline | candidate | delta | samples | minutes | rule | final | notes |
|---|---|---|---|---|---|---|---|---|---|
## Notes from write-ups
```

A manifest names its pattern in `patternId`; `ingest` uses it to find the
file, and creates a stub (`stage: unknown`) for an id that has no file yet so
nothing is lost. The Measured row's `notes` carries the error kinds of a
rejected candidate, which is how the checklist grows.

## Validation

Train on two problems, hold one out: with the corpus available versus
hidden, compare time to first promote and score at a fixed time on the
held-out problem. Until that comparison exists, the corpus is a cost, not
a result.
