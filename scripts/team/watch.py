#!/usr/bin/env python3
"""Wait until one of this session's tasks changes on the central ledger, print it, and exit.

Polls the read-only task-list through control.py (no ledger event is written), so a
member learns that the integrator returned, finished or handed over its work without
re-reading by hand. Run it in the background or under a monitor; it exits on the first change.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
WATCHED = ('status', 'owner', 'reason', 'source_sha')


def mine(tasks, agent):
    return {t['id']: {k: t.get(k) for k in WATCHED} for t in tasks if t.get('owner') == agent}


def changes(before, after):
    result = []
    for task_id in sorted(set(before) | set(after)):
        old, new = before.get(task_id), after.get(task_id)
        if old != new:
            result.append({'id': task_id, 'before': old, 'after': new})
    return result


def task_list(where, agent):
    out = subprocess.run([sys.executable, str(ROOT / 'scripts/team/control.py'), *where,
                          'task-list', '--agent', agent],
                         capture_output=True, text=True, timeout=120)
    if out.returncode:
        detail = (out.stderr or out.stdout).strip()
        raise ValueError(f'task-list failed (exit {out.returncode}): {detail[-2000:]}')
    return json.loads(out.stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    where = p.add_mutually_exclusive_group()
    where.add_argument('--host-config')
    where.add_argument('--env')
    p.add_argument('--agent', required=True)
    p.add_argument('--interval', type=int, default=60, help='seconds between polls (minimum 15)')
    p.add_argument('--max-minutes', type=int, default=60)
    a = p.parse_args()
    flags = ['--host-config', a.host_config] if a.host_config else ['--env', a.env] if a.env else []
    deadline = time.monotonic() + a.max_minutes * 60
    try:
        before = mine(task_list(flags, a.agent), a.agent)
        while time.monotonic() < deadline:
            time.sleep(max(15, a.interval))
            found = changes(before, mine(task_list(flags, a.agent), a.agent))
            if found:
                print(json.dumps({'agent': a.agent, 'changes': found}, ensure_ascii=False))
                return 0
        print(json.dumps({'agent': a.agent, 'changes': [], 'timeout': True}))
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
