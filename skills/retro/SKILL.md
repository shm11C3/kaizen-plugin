---
name: retro
description: "Capture ISUCON failures and recurring friction. Refine reusable skills during practice; preserve practice problem-specific procedures as knowledge. During competition also turn target-specific recurring work into tested skills through improve-workflow and private plugin-main integration."
---

# Retro

Set `K` to this skill's plugin root (`../..`) and export `KAIZEN_PROJECT`.
Read `../../team/docs/WORKFLOW.md` for the mode and change policy.

```bash
"$K/scripts/retro.sh" list
"$K/scripts/retro.sh" note "observed friction and evidence reference"
```

Scripts capture refusals and unexpected failures in `.kaizen/friction.jsonl`.
Add unclear instructions, repeated commands and workarounds. Separate a correct
guard, a misleading instruction, a defect, a missed signal and a candidate failure.

During **practice**, classify reusable versus problem/environment-specific work.
For the specific work, save artifact references, diagnosis, proposed remedy,
validation and payoff in the shared knowledge directory's `lessons/`, using
`../../team/templates/WORKFLOW.md`. Link error investigations and later recovery
experiments. Keep that problem-specific procedure as knowledge. For reusable
skill/procedure improvements, use `../improve-workflow/SKILL.md`, validate
against another problem or fixture, and integrate through plugin main.

After saving, acknowledge captured entries if the Stop hook requires them handled,
without claiming that the defect was fixed:

```bash
"$K/scripts/retro.sh" resolve ID --fix "knowledge-only: LESSON_REFERENCE; implementation deferred"
```

Here `resolve` acknowledges reporting; the lesson remains visibly unimplemented.
Do not invent a fixing commit.

During **competition**, use `../improve-workflow/SKILL.md`: build worthwhile
automation in the editable plugin source on a separate branch, test, integrate
into plugin main through its release owner, then roll out a pinned release at
an idle boundary. Resolve with the actual fixing commit. Application candidates
continue through the usual experiment loop.

Neither reusable self-improvement nor a separate human development request
changes an active comparison's frozen plugin, inputs or rules. Record a new
release separately and evaluate it in a subsequent trial.
