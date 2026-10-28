"""Exercise shared ownership, real process overlap and repair/retest history."""
import concurrent.futures
import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ParallelQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'shared.sqlite3'
        self.plugin = self.root / 'plugin'
        (self.plugin / 'scripts').mkdir(parents=True)
        (self.plugin / 'knowledge/patterns').mkdir(parents=True)
        (self.plugin / 'knowledge/match.py').write_text('# seed\n')

    def cli(self, *args, environment='competition', ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db),
                                 '--environment', environment, *args], capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def config(self, name, resources=None):
        project = self.root / name
        (project / '.kaizen').mkdir(parents=True)
        (project / '.kaizen/config.sh').write_text('# independent fixture\n')
        path = self.root / (name + '.json')
        path.write_text(json.dumps(dict(environment=name, resources=resources or ['host:' + name],
            enabled=True, confirmed_rules=True, confirmed_recovery_drill=True,
            project=str(project), plugin_root=str(self.plugin), knowledge_dir=str(project / 'knowledge'))))
        return path

    def register(self, name, path):
        return self.cli('env-register', '--agent', 'setup', '--config', str(path), '--reason',
                        'fixture: independent hosts, DB, mock and load-generator CPU', environment=name)

    def acquire(self, name, owner):
        return self.cli('env-acquire', '--agent', owner, '--purpose', 'validation', environment=name)['token']

    def target(self, name, owner, token, path, *args):
        return [sys.executable, str(ROOT / 'scripts/team/target.py'), '--db', str(self.db),
                '--environment', name, '--agent', owner, '--token', token, '--config', str(path), *args]

    def test_inventory_prevents_overlap_and_config_retargeting(self):
        official = self.config('competition', ['aws:app', 'aws:db', 'aws:bench'])
        sandbox = self.config('lane-a', ['aws:other-app', 'aws:bench'])
        self.cli('env-register', '--agent', 'setup', '--config', str(sandbox), '--reason', 'fixture',
                 environment='lane-a', ok=False)
        self.register('competition', official)
        self.cli('env-register', '--agent', 'setup', '--config', str(sandbox), '--reason', 'fixture',
                 environment='lane-a', ok=False)
        data = json.loads(sandbox.read_text()); data['resources'] = ['aws:other-app', 'aws:other-bench']
        sandbox.write_text(json.dumps(data)); self.register('lane-a', sandbox)
        token = self.acquire('lane-a', 'worker')
        (self.plugin / 'scripts/status.sh').write_text('touch invoked\n')
        # Same path with changed host preset is no longer the registered target.
        (self.root / 'lane-a/.kaizen/config.sh').write_text('# changed host binding\n')
        result = subprocess.run(self.target('lane-a', 'worker', token, sandbox, 'status'), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('re-register', result.stderr)
        self.assertFalse((self.root / 'lane-a/invoked').exists())
        self.cli('env-register', '--agent', 'setup', '--config', str(sandbox), '--reason', 'fixture',
                 environment='lane-a', ok=False)

    def test_distinct_targets_overlap_same_target_and_release_remain_locked(self):
        configs = {name: self.config(name) for name in ('competition', 'lane-a', 'lane-b')}
        for name, config in configs.items():
            self.register(name, config)
        tokens = {name: self.acquire(name, name) for name in ('lane-a', 'lane-b')}
        # The first process waits for the second to enter its actual target script.
        # This barrier fails if target.py still has one global operation lock.
        script = ('#!/bin/bash\nset -eu\n' + sys.executable + " - <<'PY'\n"
                  'from pathlib import Path\nimport time\n'
                  'p=Path.cwd(); (p/"entered").touch()\n'
                  'other=p.parent/("lane-b" if p.name=="lane-a" else "lane-a")/"entered"\n'
                  'deadline=time.monotonic()+4\n'
                  'while not other.exists():\n'
                  '    if time.monotonic()>deadline: raise RuntimeError("targets did not overlap")\n'
                  '    time.sleep(.01)\n'
                  'while not (p/"finish").exists(): time.sleep(.01)\n'
                  '(p/"completed").touch()\nPY\n')
        (self.plugin / 'scripts/status.sh').write_text(script)
        processes = []
        try:
            for name in tokens:
                processes.append(subprocess.Popen(self.target(name, name, tokens[name], configs[name], 'status'),
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 4
            while not all((self.root / n / 'entered').exists() for n in tokens):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            collision = subprocess.run(self.target('lane-a', 'lane-a', tokens['lane-a'], configs['lane-a'], 'status'),
                                       capture_output=True, text=True)
            self.assertNotEqual(collision.returncode, 0)
            self.cli('env-release', '--agent', 'lane-a', '--token', tokens['lane-a'], '--reason', 'too early',
                     environment='lane-a', ok=False)
            # Task ownership still uses the very same shared ledger from either lane.
            task = self.cli('task-create', '--title', 'one hypothesis', '--evidence', 'trace')['id']
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda name: subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db), '--environment', name,
                     'task-claim', '--id', task, '--agent', name], capture_output=True, text=True), tokens))
            self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        finally:
            for name in tokens:
                (self.root / name / 'finish').touch()
            for process in processes:
                try:
                    _, stderr = process.communicate(timeout=6)
                except subprocess.TimeoutExpired:
                    process.kill(); process.communicate(); raise
                self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(all((self.root / n / 'completed').exists() for n in tokens))

    def test_portal_reservation_is_scoped_but_survives_between_commands(self):
        configs = {n: self.config(n) for n in ('competition', 'lane-a', 'lane-b')}
        for n, c in configs.items():
            self.register(n, c)
        tokens = {n: self.acquire(n, n) for n in ('lane-a', 'lane-b')}
        (self.plugin / 'scripts/bench.sh').write_text(
            'set -eu\nif [ "$2" = --reserve ]; then echo pending > .kaizen/manual-bench.json; '
            'else rm .kaizen/manual-bench.json; fi\n')
        for flag in ('--reserve', '--abandon'):
            result = subprocess.run(self.target('lane-a', 'lane-a', tokens['lane-a'], configs['lane-a'],
                                                'bench', 'candidate', flag), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if flag == '--reserve':
                self.cli('env-handoff', '--agent', 'lane-a', '--token', tokens['lane-a'], '--to', 'other',
                         '--reason', 'not finished', environment='lane-a', ok=False)
                self.cli('env-release', '--agent', 'lane-b', '--token', tokens['lane-b'], '--reason', 'idle',
                         environment='lane-b')
        self.cli('env-release', '--agent', 'lane-a', '--token', tokens['lane-a'], '--reason', 'ended', environment='lane-a')

    def test_quality_hold_repairs_require_official_passing_record_and_keep_history(self):
        official = self.config('competition'); sandbox = self.config('lane-a')
        project = self.root / 'competition'
        def git(*args):
            return subprocess.check_output(['git', '-C', str(project), *args], text=True, stderr=subprocess.PIPE).strip()
        git('init', '-q', '-b', 'main')
        git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@example.invalid')
        git('config', 'commit.gpgsign', 'false')
        (project / '.git/info/exclude').write_text('.kaizen/\n')
        (project / 'go').mkdir()
        def commit(value):
            (project / 'go/source').write_text(value)
            git('add', '.'); git('commit', '-qm', value)
            return git('rev-parse', 'HEAD')
        base, source, repaired = [commit(value) for value in ('base', 'known failure', 'repaired')]
        (project / 'README.md').write_text('metadata composition')
        git('add', '.'); git('commit', '-qm', 'integrated metadata')
        tested = git('rev-parse', 'HEAD')
        (project / '.kaizen/stable-bundle.json').write_text(json.dumps(dict(trees={'go': None})))
        self.register('competition', official); self.register('lane-a', sandbox)
        official_token = self.acquire('competition', 'integrator')
        lane_token = self.acquire('lane-a', 'worker')
        task = self.cli('task-create', '--title', 'fast but errors', '--evidence', 'observations')['id']
        self.cli('task-claim', '--id', task, '--agent', 'worker')
        def ready(sha):
            self.cli('task-ready', '--id', task, '--agent', 'worker', '--base', base,
                     '--sha', sha, '--review', 'auto', '--reason', 'candidate with tests')
        ready(source)
        self.cli('task-quality-hold', '--id', task, '--agent', 'worker', '--token', lane_token,
                 '--category', 'warning', '--evidence', 'E-01/raw.log CODE26; requests unknown',
                 '--reason', 'isolate timestamp visibility', environment='lane-a')
        finish = ('task-finish', '--id', task, '--agent', 'integrator', '--result', 'ACCEPTED', '--reason', 'retest')
        self.cli(*finish, ok=False)
        self.cli('task-resume', '--id', task, '--agent', 'worker', '--reason', 'move timestamp near commit')
        ready(repaired)
        hold = self.cli('status')['quality_holds'][0]
        self.assertEqual((hold['source_sha'], hold['repair_sha'], hold['state']), (source, repaired, 'RETEST_PENDING'))
        self.cli('task-finish', '--id', task, '--agent', 'worker', '--result', 'ACCEPTED',
                 '--reason', 'sandbox score rose', environment='lane-a', ok=False)
        directory = self.root / 'competition/.kaizen/experiments/002-retest'
        directory.mkdir(parents=True)
        record = directory / 'record.json'
        data = dict(finalDecision='promote', candidateRevision=tested, stableAfter=tested,
                    manifest=dict(candidateRevision=tested),
                    closedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    ruleDecision=dict(quality=dict(status='unknown'), qualityBlockPromotion=True))
        data['samples'] = [{'label': 'candidate', 'pass': True, 'deployedRevision': tested,
                            'finishedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()}]
        record.write_text(json.dumps(data))
        self.cli(*finish, '--record', str(record), '--tested-sha', tested, ok=False)
        data['ruleDecision'] = dict(quality=dict(status='pass'), qualityBlockPromotion=False)
        record.write_text(json.dumps(data))
        self.cli(*finish, '--record', str(record), '--tested-sha', '5'*40, ok=False)
        # A good sandbox record is still not an official adoption record.
        other = self.root / 'lane-a/record.json'; other.write_text(record.read_text())
        self.cli(*finish, '--record', str(other), '--tested-sha', tested, ok=False)
        data['closedAt'] = '2020-01-01T00:00:00Z'; record.write_text(json.dumps(data))
        self.cli(*finish, '--record', str(record), '--tested-sha', tested, ok=False)
        data['closedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat(); record.write_text(json.dumps(data))
        data['samples'].append({'label': 'baseline-3', 'pass': True, 'deployedRevision': base})
        data['samples'].append({'label': 'candidate-observed', 'pass': True, 'observed': True, 'deployedRevision': '6'*40})
        record.write_text(json.dumps(data))
        self.cli('task-finish', '--id', task, '--agent', 'integrator', '--result', 'NEEDS_HUMAN',
                 '--question', 'Accept the measured latency tradeoff?', '--reason', 'safe comparison complete')
        self.cli(*finish, '--record', str(record), '--tested-sha', tested,
                 '--human-decision', 'fixture: actual human choice', ok=False)
        data['manifest']['review'] = 'human'; data['humanDecision'] = 'fixture: actual human choice'
        record.write_text(json.dumps(data))
        self.cli(*finish, '--record', str(record), '--tested-sha', tested,
                 '--human-decision', 'fixture: actual human choice')
        hold = self.cli('status')['quality_holds'][0]
        self.assertEqual((hold['source_sha'], hold['repair_sha'], hold['tested_sha'], hold['state']),
                         (source, repaired, tested, 'RESOLVED'))
        self.cli('task-quality-hold', '--id', task, '--agent', 'integrator', '--token', official_token,
                 '--category', 'warning', '--evidence', 'later warning', '--reason', 'recurrence', ok=False)
        followup = self.cli('task-create', '--related', task, '--title', 'recurrence', '--kind', 'investigation',
                            '--evidence', 'later restart warning')
        self.assertEqual(followup['related_task'], task)
        self.assertEqual(self.cli('task-list')[0]['status'], 'ACCEPTED')

    def test_failed_retest_supersedes_the_earlier_hold(self):
        token = self.acquire('competition', 'integrator')
        task = self.cli('task-create', '--title', 'index', '--evidence', 'e')['id']
        self.cli('task-claim', '--id', task, '--agent', 'worker')
        self.cli('task-ready', '--id', task, '--agent', 'worker', '--base', '1'*40, '--sha', '2'*40,
                 '--review', 'auto', '--reason', 'candidate')
        self.cli('task-quality-hold', '--id', task, '--agent', 'integrator', '--token', token,
                 '--category', 'timeout', '--evidence', 'error25', '--reason', 'first')
        self.cli('task-resume', '--id', task, '--agent', 'worker', '--reason', 'repair')
        self.cli('task-ready', '--id', task, '--agent', 'worker', '--base', '1'*40, '--sha', '3'*40,
                 '--review', 'auto', '--reason', 'repaired')
        self.cli('task-quality-hold', '--id', task, '--agent', 'integrator', '--token', token,
                 '--category', 'unknown', '--evidence', 'error25 again', '--reason', 'retest failed')
        holds = sorted(self.cli('status')['quality_holds'], key=lambda h: h['id'])
        self.assertEqual([(h['state'], h['source_sha'][:1]) for h in holds], [('SUPERSEDED', '2'), ('OPEN', '3')])
        self.assertIn('#' + str(holds[1]['id']), holds[0]['retest_record'])

    def test_stacking_on_a_held_source_warns(self):
        # Practice: T-0007/T-0009 were built on T-0001's source while it sat in a quality hold.
        token = self.acquire('competition', 'integrator')
        held = self.cli('task-create', '--title', 'index', '--evidence', 'observation')['id']
        self.cli('task-claim', '--id', held, '--agent', 'worker')
        self.cli('task-ready', '--id', held, '--agent', 'worker', '--base', '1'*40, '--sha', '2'*40,
                 '--review', 'auto', '--reason', 'candidate')
        self.cli('task-quality-hold', '--id', held, '--agent', 'integrator', '--token', token,
                 '--category', 'timeout', '--evidence', 'error25 rose', '--reason', 'freshness')
        stacked = self.cli('task-create', '--title', 'nearby', '--evidence', 'e')['id']
        self.cli('task-claim', '--id', stacked, '--agent', 'worker')
        result = self.cli('task-ready', '--id', stacked, '--agent', 'worker', '--base', '2'*40, '--sha', '3'*40,
                          '--review', 'auto', '--reason', 'stacked')
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn(held, result['warnings'][0])
        free = self.cli('task-create', '--title', 'other', '--evidence', 'e')['id']
        self.cli('task-claim', '--id', free, '--agent', 'worker')
        self.assertNotIn('warnings', self.cli('task-ready', '--id', free, '--agent', 'worker', '--base', '1'*40,
                                              '--sha', '4'*40, '--review', 'auto', '--reason', 'on stable'))

    def test_abandoned_quality_work_retains_failure_without_becoming_resolved(self):
        token = self.acquire('competition', 'integrator')
        task = self.cli('task-create', '--title', 'unsafe candidate', '--evidence', 'observation')['id']
        self.cli('task-claim', '--id', task, '--agent', 'worker')
        self.cli('task-ready', '--id', task, '--agent', 'worker', '--base', '1'*40, '--sha', '2'*40,
                 '--review', 'auto', '--reason', 'candidate')
        self.cli('task-quality-hold', '--id', task, '--agent', 'integrator', '--token', token,
                 '--category', 'correctness', '--evidence', 'raw: pass=false', '--reason', 'state mismatch')
        self.cli('task-finish', '--id', task, '--agent', 'integrator', '--result', 'REJECTED',
                 '--reason', 'repair cost exceeds remaining time; stable restored')
        hold = self.cli('status')['quality_holds'][0]
        self.assertEqual((hold['state'], hold['source_sha'], hold['evidence']),
                         ('ABANDONED', '2'*40, 'raw: pass=false'))
        self.assertIsNone(hold['retest_record'])


if __name__ == '__main__':
    unittest.main()
