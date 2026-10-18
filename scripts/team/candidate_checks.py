"""Run configured native QA on one frozen candidate, retaining check.py evidence."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

CHECK = Path(__file__).resolve().parents[1] / 'check.py'
_spec = importlib.util.spec_from_file_location('kaizen_native_check', CHECK)
_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check)


def git(project, *arguments):
    result = subprocess.run(['git', '-C', str(project), *arguments], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('candidate QA Git operation failed: ' + result.stderr.strip()[-500:])
    return result.stdout.strip()


def settings(checks):
    if not isinstance(checks, list):
        raise ValueError('checks must be a list')
    normalized = []
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get('label'), str) or not re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', item['label']):
            raise ValueError('each check needs a safe label')
        command, cwd = item.get('command'), item.get('cwd', '.')
        timeout, advisory = item.get('timeout_seconds', 120), item.get('advisory', False)
        diagnostics = item.get('diagnostics')
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
            raise ValueError('check command must be a nonempty argv list')
        if not isinstance(cwd, str) or not cwd or Path(cwd).is_absolute() or '..' in Path(cwd).parts:
            raise ValueError('check cwd must stay inside the project')
        if type(timeout) is not int or timeout <= 0 or type(advisory) is not bool:
            raise ValueError('check timeout must be positive and advisory must be boolean')
        if diagnostics not in (None, 'gofmt', 'cargo'):
            raise ValueError('check diagnostics must be gofmt or cargo')
        normalized.append(dict(label=item['label'], command=command, cwd=cwd,
                               timeout_seconds=timeout, diagnostics=diagnostics, advisory=advisory))
    return normalized


def copy_immutable(source, destination):
    with Path(source).open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)


def run_checks(project, candidate, checks, state_dir):
    """Return receipts; native diagnostics stay intact and source failure is explicit.

    All checks run, including after a failure. One disposable worktree isolates
    check artifacts and mutations from the integration checkout. Callers must
    always block sourceIntegrityPassed=False, even for declared advisory checks.
    """
    project, state_dir = Path(project).resolve(), Path(state_dir).resolve()
    configured = settings(checks)
    if not isinstance(candidate, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', candidate):
        raise ValueError('candidate QA needs a full SHA')
    candidate = candidate.lower()
    if git(project, 'rev-parse', 'HEAD') != candidate:
        raise ValueError('candidate QA source does not match HEAD')
    if git(project, 'status', '--porcelain', '--untracked-files=all', '--', '.',
           ':(exclude).kaizen/**', ':(exclude).study/**'):
        raise ValueError('candidate QA requires clean committed source')
    expected = _check.source(project)
    if not configured:
        return []
    output = state_dir / 'checks' / candidate
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    cache_inherited = 'CARGO_TARGET_DIR' in environment
    if not cache_inherited:
        environment['CARGO_TARGET_DIR'] = str(state_dir / 'check-cache/cargo')
    cache = dict(cargoTargetDir=environment['CARGO_TARGET_DIR'], inherited=cache_inherited,
                 note='Persistent default across candidates; inherited CARGO_TARGET_DIR and Go cache settings are preserved.')
    receipts = []
    with tempfile.TemporaryDirectory(prefix='candidate-qa-', dir=state_dir) as temporary:
        worktree = Path(temporary).resolve()
        git(project, 'worktree', 'add', '--detach', str(worktree), candidate)
        try:
            for item in configured:
                cwd = (worktree / item['cwd']).resolve()
                if not cwd.is_relative_to(worktree) or not cwd.is_dir():
                    raise ValueError('check cwd is not a project directory')
                stem = item['label'] + '-' + uuid.uuid4().hex
                log, native_record, record = [output / (stem + suffix) for suffix in ('.log', '-native.json', '.json')]
                before = _check.source(worktree)
                arguments = [sys.executable, str(CHECK), '--project', str(cwd), '--label', item['label'],
                             '--timeout', str(item['timeout_seconds'])]
                if item['diagnostics']:
                    arguments += ['--diagnostics', item['diagnostics']]
                started = time.monotonic()
                native, error, launched = None, None, None
                try:
                    launched = subprocess.run([*arguments, '--', *item['command']], capture_output=True,
                                              text=True, env=environment)
                    parsed = json.loads(launched.stdout)
                    if not isinstance(parsed, dict):
                        raise ValueError('check launcher did not return an object')
                    native = parsed
                    # check.py exit 3 is an advisory diagnostic, not a launcher failure.
                    if (native.get('status') not in ('passed', 'failed', 'needs_review')
                            or launched.returncode != {'passed': 0, 'failed': 2, 'needs_review': 3}[native['status']]):
                        raise ValueError('invalid check launcher result')
                    paths = [Path(native[key]).resolve() for key in ('record', 'log')]
                    artifacts = cwd / '.kaizen/checks'
                    if any(not path.is_relative_to(artifacts) for path in paths):
                        raise ValueError('check launcher evidence is outside its artifact directory')
                    copy_immutable(paths[0], native_record)
                    copy_immutable(paths[1], log)
                    # Nested cwd metadata is not application source. Preserve the
                    # evidence above, then remove only these generated copies
                    # before checking the whole application's source fingerprint.
                    for path in paths:
                        path.unlink()
                    for path in (artifacts, cwd / '.kaizen'):
                        try:
                            path.rmdir()
                        except OSError:
                            pass
                except (OSError, ValueError, TypeError, KeyError) as failure:
                    error = str(failure)
                    if not log.exists():
                        with log.open('x') as stream:
                            stream.write(error + '\n')
                            if launched is not None:
                                stream.write(launched.stdout + launched.stderr)
                after = _check.source(worktree)
                integrity = (before == after == expected and native is not None
                             and isinstance(native.get('sourceBefore'), dict)
                             and isinstance(native.get('sourceAfter'), dict)
                             and native['sourceBefore'].get('revision') == native['sourceAfter'].get('revision') == candidate
                             and native['sourceBefore'] == native['sourceAfter'] and native.get('sourceChanged') is False)
                receipt = dict(label=item['label'], command=item['command'], cwd=item['cwd'],
                               declaredAdvisory=item['advisory'], sourceIntegrityPassed=integrity,
                               source=dict(expected=expected, before=before, after=after),
                               status='failed' if error or not integrity else native['status'],
                               nativeResult=native, launcherError=error,
                               cache=cache,
                               durationSeconds=round(time.monotonic() - started, 6),
                               record=str(record), nativeRecord=str(native_record) if native_record.exists() else None,
                               log=str(log))
                with record.open('x') as stream:
                    json.dump(receipt, stream, indent=2, ensure_ascii=False)
                    stream.write('\n')
                receipts.append(receipt)
                if after != expected:
                    # Restore only our disposable source; later QA still checks
                    # the declared candidate, while the failed evidence remains.
                    git(worktree, 'reset', '--hard', candidate)
                    git(worktree, 'clean', '-fd', '--', '.', ':(exclude).kaizen/**', ':(exclude).study/**')
        finally:
            subprocess.run(['git', '-C', str(project), 'worktree', 'remove', '--force', str(worktree)],
                           capture_output=True)
    return receipts
