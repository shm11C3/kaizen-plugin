---
name: knowledge
description: "Use the measured pattern corpus. Before a hypothesis, match an observation dump against the pattern signatures and read the matching pattern files; after an experiment, confirm it was ingested and improve the pattern file (checklist, signature) from what happened. Also the place to add a new pattern from a write-up or an official 解説."
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

## Adding a pattern

A pattern comes from something this loop observed or tried, or from a
published 解説 / write-up you read. Either way, write it in your own words:
the symptom as the dump shows it, the templates, the checklist. Never paste
sentences, numbers, or scores from a source; put the link under `sources:`
and nothing else. Leave **Measured** empty until the loop runs it. An
unmeasured pattern is a hypothesis; the matcher still reports it so it can
be tried and measured.

## Not bound by the corpus

The catalog is what has been seen before. When the dump's biggest cost
matches no pattern, hypothesize from the dump and give the new mechanism
its own `patternId`; ingest will create the file. A problem designed after
the catalog existed is designed to escape it.
