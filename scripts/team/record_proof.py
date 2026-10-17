"""Read adoption evidence without re-running or changing a measured decision."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess


def promoted_record(record, expected_sha):
    if (not re.fullmatch(r'[a-fA-F0-9]{40}', expected_sha)
            or record.get('finalDecision') != 'promote'
            or record.get('candidateRevision') != expected_sha
            or record.get('stableAfter') != expected_sha
            or record.get('manifest', {}).get('candidateRevision') != expected_sha
            or record.get('ruleDecision', {}).get('quality', {}).get('status') != 'pass'
            or record.get('ruleDecision', {}).get('qualityBlockPromotion') is not False):
        raise ValueError('adoption requires passing quality, promote and matching candidate/stable SHA')
    samples = [s for s in record.get('samples', [])
               if s.get('label', '').startswith('candidate') and not s.get('observed')]
    if not samples or any(s.get('pass') is not True or s.get('deployedRevision') != expected_sha for s in samples):
        raise ValueError('adoption samples must pass on the promoted source SHA')


def sync_proof(official_project, path, sandbox_project):
    official_project, path = Path(official_project).resolve(), Path(path).resolve()
    root = official_project / '.kaizen/experiments'
    if not path.is_relative_to(root.resolve()) or path.name != 'record.json':
        raise ValueError('sync record must belong to the registered competition project')
    raw = path.read_bytes()
    record = json.loads(raw)
    revision = record.get('candidateRevision', '')
    promoted_record(record, revision)
    previous = record.get('stableBefore', '')
    manifest = record['manifest']
    decision = record['ruleDecision']
    bundle = manifest.get('stableBundle', {}).get('id')
    if (not re.fullmatch(r'[a-fA-F0-9]{40}', previous)
            or manifest.get('stableRevision') != previous
            or decision.get('candidateRevisions') != [revision]
            or decision.get('baselineRevisions') != [previous]
            or not bundle or decision.get('stableBundleId') != bundle):
        raise ValueError('official decision must bind the promoted source and original stable bundle')
    candidates = [s for s in record['samples'] if s.get('label', '').startswith('candidate') and not s.get('observed')]
    if any(sample.get('stableBundleId') != bundle for sample in candidates):
        raise ValueError('candidate samples are not bound to the official comparison bundle')
    if (manifest.get('review') == 'human' or decision.get('decision') != 'promote') and not record.get('humanDecision'):
        raise ValueError('the official adoption is missing its required human decision reference')
    closed = datetime.datetime.fromisoformat(record['closedAt'].replace('Z', '+00:00'))
    if closed.tzinfo is None:
        raise ValueError('adoption record needs a timezone-aware close time')
    if json.loads((path.parent / 'manifest.json').read_text()) != record['manifest']:
        raise ValueError('record manifest differs from the original experiment proof')
    if json.loads((path.parent / 'decision.json').read_text()) != record['ruleDecision']:
        raise ValueError('record decision differs from the original experiment proof')
    samples = [json.loads(file.read_text()) for file in sorted(path.parent.glob('bench-*.json'))]
    if samples != record['samples']:
        raise ValueError('record samples differ from the original measured samples')
    state = dict(line.split('=', 1) for line in (official_project / '.kaizen/state.env').read_text().splitlines() if '=' in line)
    current = state.get('STABLE_REV', '')
    if not re.fullmatch(r'[a-fA-F0-9]{40}', current):
        raise ValueError('registered competition stable revision is missing')
    for project in (official_project, Path(sandbox_project)):
        for sha in {revision, current}:
            try:
                actual = subprocess.check_output(['git', '-C', str(project), 'rev-parse', '--verify', sha + '^{commit}'], stderr=subprocess.PIPE).decode().strip()
            except subprocess.CalledProcessError as error:
                raise ValueError('fetch the official source objects before sandbox sync') from error
            if actual != sha:
                raise ValueError('fetch the official source objects before sandbox sync')
    return {'record': str(path), 'recordSha256': hashlib.sha256(raw).hexdigest(),
            'promotedRevision': revision, 'targetRevision': current,
            'closedAt': record['closedAt'], 'officialProject': str(official_project)}
