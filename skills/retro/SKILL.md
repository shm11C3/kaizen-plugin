---
name: retro
description: Turn what broke into plugin fixes. Use after every closed experiment, whenever a script refused or failed on a real host, and before ending a practice session: reads .kaizen/friction.jsonl (written automatically by every script), fixes the plugin (script, skill, signature, checklist) with a test, and marks the entries resolved so the plugin keeps its own improvement log.
---

# Retro

Scripts: `$K/scripts/` (K = this skill's base directory `/../..`). Run with
`KAIZEN_PROJECT` exported (see setup). The plugin repository is `$K` itself.

```bash
$K/scripts/retro.sh list                 # unresolved friction, grouped, with ids
$K/scripts/retro.sh note "<what misled you>"   # friction the scripts could not see
```

Every `die` and every unexpected command failure in the scripts lands in
`.kaizen/friction.jsonl` with the script, the message, the command, and the
experiment. Add by hand what only you saw: a skill step that was unclear, a
manual workaround, a wrong assumption in a pattern checklist.

## For each group, decide what it is

| kind | example | fix goes to |
|---|---|---|
| defect | a script fails on a real host (bash 3.2, a path, a missing sudo) | `scripts/` + a case in `tests/run.sh` |
| guard that fired for a good reason | "no baseline sample", "budget" | nothing, or a clearer message |
| guard that fired because the skill led you wrong | you ran bench before baseline because the skill said so | the skill text |
| missed signal | the dump showed a bottleneck the matcher did not name | `knowledge/signatures.py` + the pattern's `signature:` |
| broke correctness | a candidate failed the benchmark | the pattern's Checklist, with the experiment id |

## Fix, test, resolve

Make the change in the plugin repository on the current branch (practice:
`corpus/<problem>` or `fix/real-run`; never `main` directly), run
`$K/tests/run.sh`, commit with a message that names the friction, then:

```bash
$K/scripts/retro.sh resolve <id> <id> --fix <commit sha>
$K/scripts/retro.sh resolve <id> --fix "guard correct; message reworded"   # when no code changed
```

Resolutions append to `$K/retro/log.md`: the plugin's own record of what
real targets taught it. The Stop hook asks for a retro when unresolved
entries pile up (`RETRO_BLOCK_AFTER` in config.sh, default 5); on contest
day set it high and run the retro afterwards.
