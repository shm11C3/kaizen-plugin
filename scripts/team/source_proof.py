"""Conservative, Git-backed source and inherited quality-hold checks.

Blob identity proves preserved source, not semantic correctness. A composition
that edits a submitted file again must submit its actual integrated SHA.
"""
import datetime
import json
from pathlib import Path
import re
import subprocess


class SourceProof:
    def __init__(self, project):
        self.project = Path(project)
        bundle = json.loads((self.project / '.kaizen/stable-bundle.json').read_text())
        self.paths = list(bundle.get('trees', {}))
        if not self.paths or any(not isinstance(p, str) or not p or p.startswith(('/', ':'))
                                 or '..' in Path(p).parts for p in self.paths):
            raise ValueError('source proof needs the captured deployable paths in the stable bundle')
        self.cache = {}

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.project), *args], capture_output=True)
        if result.returncode:
            raise ValueError('source proof needs available Git objects; fetch submitted and held sources')
        return result.stdout

    def commit(self, sha):
        if not isinstance(sha, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', sha):
            raise ValueError('source proof needs full base, submitted and tested SHAs')
        if self.git('rev-parse', '--verify', sha + '^{commit}').decode().strip().lower() != sha.lower():
            raise ValueError('source proof SHA does not identify the expected commit')

    def entries(self, sha):
        if sha not in self.cache:
            self.commit(sha)
            entries = {}
            for entry in self.git('ls-tree', '-r', '-z', '--full-tree', sha, '--', *self.paths).split(b'\0'):
                if entry:
                    value, path = entry.split(b'\t', 1)
                    entries[path] = value
            self.cache[sha] = entries
        return self.cache[sha]

    def same(self, first, second):
        return self.entries(first) == self.entries(second)

    def contains(self, base, source, tested):
        """Allow exact deployed content or preserved base→source changed blobs.

        This accepts non-overlapping cherry-picks and refuses a plain revert,
        even when source is an ancestor of tested. Deletions and modes count.
        """
        original, submitted, candidate = self.entries(base), self.entries(source), self.entries(tested)
        if submitted == candidate:
            return True
        changed = {path for path in original.keys() | submitted.keys() if original.get(path) != submitted.get(path)}
        return bool(changed) and all(candidate.get(path) == submitted.get(path) for path in changed)

    def ancestor(self, source, tested):
        self.commit(source); self.commit(tested)
        result = subprocess.run(['git', '-C', str(self.project), 'merge-base', '--is-ancestor', source, tested],
                                capture_output=True)
        if result.returncode not in (0, 1):
            raise ValueError('cannot establish held source ancestry')
        return result.returncode == 0


def inherited_holds(db, proof, candidate):
    # Closed history stays available for AI investigation; this bounded guard
    # handles live holds and does not invent a workflow for reopening history.
    return [dict(h) for h in db.execute("SELECT * FROM quality_holds WHERE state IN ('OPEN','RETEST_PENDING') ORDER BY id")
            if proof.ancestor(h['source_sha'], candidate) or proof.same(h['source_sha'], candidate)
            or proof.contains(h['base_sha'], h['source_sha'], candidate)]


SOFT_CATEGORIES = ('warning', 'timeout', 'unknown')


def guard_holds(db, proof, candidate, stabilized=False):
    """stabilized: the fixed rule adopted this measurement with a stabilization task.

    A soft (non-correctness) hold is then carried by that task instead of requiring
    changed repair content: practice T-0004 was judged promote (+35%, worst sample
    above the best baseline) twice and blocked twice on the same-content check.
    """
    holds = inherited_holds(db, proof, candidate)
    for hold in holds:
        repair = hold['repair_sha']
        if stabilized and hold['category'] in SOFT_CATEGORIES:
            continue
        if (hold['state'] != 'RETEST_PENDING' or not repair
                or not proof.contains(hold['source_sha'], repair, candidate)):
            raise ValueError('candidate inherits unresolved quality hold H-{} from T-{:04d}; '
                             'repair/resubmit that task before competition promotion'.format(hold['id'], hold['task_id']))
        if hold['category'] != 'conditions' and proof.same(hold['source_sha'], repair):
            raise ValueError('quality hold H-{} needs changed repair content; fresh clean samples alone do not repair it'.format(hold['id']))
    return holds


def fresh_retest_samples(holds, samples):
    pending = [h for h in holds if h['state'] == 'RETEST_PENDING']
    if not pending:
        return
    try:
        submitted = max(datetime.datetime.fromisoformat(h['repair_submitted_at']) for h in pending)
        candidates = [s for s in samples if s.get('label', '').startswith('candidate') and not s.get('observed')]
        fresh = bool(candidates) and all(datetime.datetime.fromisoformat(s['finishedAt'].replace('Z', '+00:00'))
                                         >= submitted.replace(microsecond=0) for s in candidates)
    except (KeyError, TypeError, ValueError):
        fresh = False
    if not fresh:
        raise ValueError('repair retest needs fresh candidate samples after repair submission')
