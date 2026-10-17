---
name: knowledge
description: Use the measured pattern corpus. Before a hypothesis, match an observation dump against the pattern signatures and read the matching pattern files; after an experiment, confirm it was ingested and improve the pattern file (checklist, signature) from what happened. Also the place to add a new pattern from a write-up or an official 解説.
---

# Knowledge

Scripts: `$K/scripts/` and the corpus `$K/knowledge/` (K = this skill's
base directory `/../..`).

## Before hypothesizing

```bash
$K/scripts/knowledge.sh match .kaizen/experiments/<id>/observe-<name>.txt   # or the dump path observe.sh printed
```

Read the ranked patterns and the evidence lines. Open the pattern file of
each candidate you consider (`knowledge/patterns/<id>.md`): the Measured
table says what it paid before and how often it failed; the Checklist says
what to verify in the change. Put the chosen `patternId` in the manifest.
When the dump shows a pattern the matcher missed, add the rule to
`knowledge/signatures.py` (one sentence, one function) and the same sentence
to the pattern file's `signature:`.

## After an experiment

`experiment.sh record` runs `knowledge.sh ingest` itself; `knowledge.sh
stats` shows the row landed. Then spend two minutes on the pattern file:

- a reject or inconclusive adds one line to **Checklist** saying what broke
  or why the effect did not show, with the experiment id;
- a promote whose change differed from the **Change template** updates the
  template;
- a stub pattern created by ingest (`stage: unknown`) gets a name, stage,
  cost, risk, and a signature sentence.

Keep the pattern files short; evidence is in `records/`, not in prose.

## Adding a pattern from the internet

Official 解説 (isucon.net) and top-team write-ups name the planted
bottlenecks. Create `knowledge/patterns/<id>.md` from the contract in
`knowledge/README.md`, cite the URL under `sources:`, write the symptom and
templates, leave **Measured** empty. An unmeasured pattern is a hypothesis;
the matcher still reports it so it can be tried and measured.
