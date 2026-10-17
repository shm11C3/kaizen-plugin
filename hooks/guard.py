#!/usr/bin/env python3
"""Mechanical guard for the kaizen loop (Claude Code hook adapter).

The scripts under scripts/ already refuse unsafe sequences; this hook stops
the agent from going around them. It never judges hypotheses or scores.

PreToolUse (Bash, Write, Edit, MultiEdit) denies:
- benchmarks, restarts, and file pushes that bypass scripts/bench.sh,
  deploy.sh, recover.sh (every sample and every deploy must be recorded);
- deploy.sh / bench.sh / recover.sh while the bench lock is held;
- writes to decision.json, record.json, bench-*.json, baseline/, state.env
  (written only by evaluate.sh, experiment.sh, bench.sh);
- git reset --hard and git push --force in the target repository.
Stop blocks the turn from ending while a candidate is deployed without a
recorded decision, or a failed candidate has not been recovered.
SessionStart adds the loop state as context.

Exit 0 always: a crashed hook would fail open, so errors are reported as
context, not raised.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SCRIPT = re.compile(r"scripts/(deploy|bench|recover|verify|evaluate|experiment|observe|status)\.sh\b")
LOCKED_SCRIPT = re.compile(r"scripts/(deploy|bench|recover)\.sh\b")
BENCH_BYPASS = re.compile(r"\bbench(marker)?\s+run\b|--payment-url|\bisuxbench\b|/bench\s+-", re.I)
REMOTE_TOOL = re.compile(r"\b(ssh|rsync|scp)\b")
RESTART = re.compile(r"systemctl\s+(restart|stop|start|reload)\b")
PUSH = re.compile(r"\brsync\b[^|;&]*\s\S+:\S*|\bscp\b")
GIT_DESTRUCTIVE = re.compile(r"\bgit\b[^|;&]*\b(reset\s+--hard|push\s+(-f\b|--force)|checkout\s+--\s|clean\s+-[a-z]*f)")
PROTECTED_FILE = re.compile(r"(decision|record)\.json|bench-[A-Za-z0-9_-]+\.json|state\.env|\.kaizen/baseline/")
WRITE_INDICATOR = re.compile(r">|\btee\b|sed\s+-i|\brm\b|\bmv\b|\bcp\b|\btruncate\b|open\([^)]*['\"][wa]|\bdd\b")
PROTECTED_PATH = re.compile(r"/\.kaizen/(experiments/[^/]+/(decision|record)\.json|experiments/[^/]+/bench-[^/]+\.json|state\.env|baseline/)")


def find_project(start: str | None) -> Path | None:
    path = Path(start or os.getcwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".kaizen" / "config.sh").is_file():
            return candidate
    return None


def read_state(project: Path) -> dict[str, str]:
    state: dict[str, str] = {}
    try:
        for line in (project / ".kaizen" / "state.env").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                state[key] = value
    except OSError:
        pass
    return state


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def pre_tool_use(event: dict, project: Path | None) -> None:
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit"):
        path = str(tool_input.get("file_path", ""))
        if PROTECTED_PATH.search(path):
            deny(f"{path} is written only by the kaizen scripts (bench.sh, evaluate.sh, experiment.sh); "
                 "edit manifest.json or the code instead")
        return
    if tool != "Bash":
        return
    command = str(tool_input.get("command", ""))
    if GIT_DESTRUCTIVE.search(command):
        deny("git reset --hard, checkout --, clean -f and force-push are refused in the loop: "
             "stable and candidate revisions must stay reachable; commit instead")
        return
    if PROTECTED_FILE.search(command) and WRITE_INDICATOR.search(command):
        deny("decision.json, record.json, bench-*.json, baseline/ and state.env are written only by "
             "evaluate.sh, experiment.sh and bench.sh; read them, do not rewrite them")
        return
    via_script = bool(SCRIPT.search(command))
    if not via_script:
        if BENCH_BYPASS.search(command):
            deny("run benchmarks through scripts/bench.sh <label> so the sample is recorded "
                 "and the lock is held")
            return
        if REMOTE_TOOL.search(command) and (RESTART.search(command) or PUSH.search(command)):
            deny("push files and restart services through scripts/deploy.sh <ref> (or recover.sh) "
                 "so the deployed revision is verified and recorded")
            return
    if project and LOCKED_SCRIPT.search(command) and (project / ".kaizen" / "bench.lock").is_dir():
        deny(f"a benchmark or deploy is running (lock {project / '.kaizen' / 'bench.lock'}); "
             "wait for it, or rmdir the lock only if you are sure nothing runs")
        return


def unresolved_friction(project: Path) -> int:
    try:
        return sum(1 for line in (project / ".kaizen" / "friction.jsonl").read_text().splitlines()
                   if line.strip() and not json.loads(line).get("resolved"))
    except (OSError, json.JSONDecodeError):
        return 0


def retro_block_after(project: Path) -> int:
    try:
        found = re.findall(r"^RETRO_BLOCK_AFTER=(\d+)", (project / ".kaizen" / "config.sh").read_text(), re.M)
        return int(found[-1]) if found else 5
    except OSError:
        return 5


def stop(event: dict, project: Path | None) -> None:
    if project is None or event.get("stop_hook_active"):
        return
    state = read_state(project)
    exp = state.get("CURRENT_EXPERIMENT", "")
    deployed = state.get("DEPLOYED_REV", "")
    stable = state.get("STABLE_REV", "")
    reasons = []
    if state.get("REVERT_PENDING") == "1":
        reasons.append("a failed candidate is still deployed: run scripts/recover.sh, then "
                       "scripts/evaluate.sh and scripts/experiment.sh record")
    elif exp and deployed and stable and deployed != stable:
        reasons.append(f"experiment {exp} still has its candidate deployed: scripts/evaluate.sh and "
                       "scripts/experiment.sh record <reason> (promote keeps it, anything else recovers stable)")
    elif exp:
        exp_dir = project / ".kaizen" / "experiments" / exp
        if list(exp_dir.glob("bench-*.json")) and not (exp_dir / "record.json").is_file():
            reasons.append(f"experiment {exp} has samples but no recorded decision: scripts/evaluate.sh then "
                           "scripts/experiment.sh record <reason>")
    friction = unresolved_friction(project)
    if not reasons and friction >= retro_block_after(project):
        reasons.append(f"{friction} unresolved friction entries: run the retro skill "
                       "(scripts/retro.sh list) and resolve them before stopping")
    if reasons:
        print(json.dumps({"decision": "block", "reason": "kaizen: " + "; ".join(reasons)}, ensure_ascii=False))


def session_start(project: Path | None) -> None:
    if project is None:
        return
    state = read_state(project)
    summary = (
        f"kaizen loop state in {project}: stable={state.get('STABLE_REV', '')[:7] or 'unset'} "
        f"deployed={state.get('DEPLOYED_REV', '')[:7] or 'none'} healthy={state.get('DEPLOYED_HEALTHY', '?')} "
        f"experiment={state.get('CURRENT_EXPERIMENT') or 'none'} revert_pending={state.get('REVERT_PENDING', '0')} "
        f"friction_unresolved={unresolved_friction(project)}. "
        "Use the kaizen skills (setup, observe, hypothesize, experiment, recover, status); "
        "benchmarks and deploys go through scripts/ only."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": summary}},
                     ensure_ascii=False))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    project = find_project(event.get("cwd"))
    name = event.get("hook_event_name")
    try:
        if name == "PreToolUse":
            pre_tool_use(event, project)
        elif name == "Stop":
            stop(event, project)
        elif name == "SessionStart":
            session_start(project)
    except Exception as error:  # noqa: BLE001 - a crashed hook fails open; say so instead
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name or "unknown",
                                                 "additionalContext": f"kaizen guard error: {error!r}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
