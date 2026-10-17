#!/usr/bin/env python3
"""Run an existing test tool locally and retain source-bound evidence and duration."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


def git(project, *args):
    return subprocess.check_output(['git', '-C', str(project), *args])


def source(project):
    revision = git(project, 'rev-parse', 'HEAD').decode().strip()
    patch = git(project, 'diff', '--binary', 'HEAD', '--', '.', ':(exclude).kaizen/**', ':(exclude).study/**')
    h = hashlib.sha256(revision.encode() + b'\0' + patch)
    for name in sorted(git(project, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')):
        if not name or name.startswith((b'.kaizen/', b'.study/')):
            continue
        path = project / os.fsdecode(name)
        h.update(name + b'\0')
        h.update(os.readlink(path).encode() if path.is_symlink() else path.read_bytes())
    return dict(revision=revision, treeFingerprint=h.hexdigest())


def diagnostics(mode, output):
    """Interpret native output without treating a warning-free exit as correctness."""
    if mode == 'gofmt':
        return [dict(level='format', file=line) for line in output.splitlines() if line.strip()], True
    if mode != 'cargo':
        return [], True
    findings = []
    finished = False
    valid = True
    for line in output.splitlines():
        if not line.startswith('{'):
            continue  # Cargo progress and build-script output can be non-JSON.
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            valid = False
            continue
        if not isinstance(item, dict):
            valid = False
            continue
        if item.get('reason') == 'build-finished':
            finished = item.get('success') is True
        elif item.get('reason') == 'compiler-message':
            message = item.get('message')
            if not isinstance(message, dict) or 'level' not in message:
                valid = False
                continue
            if message['level'] in ('warning', 'error', 'failure-note'):
                findings.append(dict(level=message['level'], code=message.get('code'),
                                     message=message.get('message'), spans=message.get('spans', [])))
    return findings, valid and finished


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, default=Path.cwd())
    p.add_argument('--label', required=True)
    p.add_argument('--timeout', type=int, default=120)
    p.add_argument('--diagnostics', choices=['gofmt', 'cargo'],
                   help='interpret gofmt -l or Cargo --message-format=json output; warnings need AI triage')
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command or a.timeout <= 0 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', a.label):
        p.error('provide a safe label, positive timeout and a test command after --')
    project = a.project.resolve()
    before = source(project)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    directory = project / '.kaizen/checks'
    directory.mkdir(parents=True, exist_ok=True)
    stem = a.label + '-' + uuid.uuid4().hex[:12]
    log = directory / (stem + '.log')
    record = directory / (stem + '.json')
    start = time.monotonic()
    timed_out = interrupted = False
    with log.open('wb') as output:
        try:
            process = subprocess.Popen(command, cwd=project, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=a.timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                timed_out = isinstance(error, subprocess.TimeoutExpired)
                interrupted = not timed_out
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                code = 124 if timed_out else 130
        except OSError as error:
            output.write(str(error).encode()); code = 127
    after = source(project)
    findings, complete = diagnostics(a.diagnostics, log.read_text(errors='replace') if a.diagnostics else '')
    process_passed = code == 0 and before == after
    errors = any(item['level'] in ('error', 'failure-note') for item in findings)
    status = ('failed' if not process_passed or not complete or errors else
              'needs_review' if findings else 'passed')
    result = dict(label=a.label, command=command, project=str(project), startedAt=started,
                  durationSeconds=round(time.monotonic()-start, 6), timeoutSeconds=a.timeout,
                  exitCode=code, timedOut=timed_out, interrupted=interrupted,
                  sourceBefore=before, sourceAfter=after, sourceChanged=before != after,
                  passed=status == 'passed', processPassed=process_passed, status=status,
                  diagnosticsMode=a.diagnostics, diagnosticsComplete=complete,
                  diagnostics=findings, log=str(log))
    record.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(record=str(record), **result), ensure_ascii=False, indent=2))
    return {'passed': 0, 'failed': 2, 'needs_review': 3}[status]


if __name__ == '__main__':
    sys.exit(main())
