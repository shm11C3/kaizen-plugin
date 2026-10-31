import json
import os
from pathlib import Path
import subprocess
import _git_test_env  # Keep fixture Git commands independent of the invoking repository.
import sys
import unittest

import test_initialize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))
from record_proof import sync_proof
from team import connect
from environments import register


class StableSyncTests(unittest.TestCase):
    def setUp(self):
        test_initialize.InitializeTarget.setUp(self)
        initial = test_initialize.InitializeTarget.initialize(self)
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        self.old = self.git(self.project, 'rev-parse', 'main').strip()
        self.official = self.directory / 'official'
        self.git(self.directory, 'clone', '-q', str(self.project), str(self.official))
        (self.official / 'app/schema').write_text('adopted schema\n')
        self.git(self.official, 'add', '.')
        self.git(self.official, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'official adoption')
        self.new = self.git(self.official, 'rev-parse', 'main').strip()
        self.git(self.project, 'fetch', '-q', str(self.official), 'main')
        folder = self.official / '.kaizen/experiments/001-adopted'
        folder.mkdir(parents=True)
        self.record_path = folder / 'record.json'
        self.data = dict(finalDecision='promote', candidateRevision=self.new, stableAfter=self.new,
                         stableBefore=self.old, closedAt='2026-10-18T00:00:00Z',
                         manifest=dict(candidateRevision=self.new, stableRevision=self.old, stableBundle=dict(id='fixture-bundle')),
                         ruleDecision=dict(decision='promote', quality=dict(status='pass'), qualityBlockPromotion=False,
                                           candidateRevisions=[self.new], baselineRevisions=[self.old], stableBundleId='fixture-bundle'),
                         samples=[dict(label='candidate-1', deployedRevision=self.new, score=200,
                                       stableBundleId='fixture-bundle', **{'pass': True})])
        self.write_proof()
        (self.official / '.kaizen/state.env').write_text('STABLE_REV=' + self.new + '\n')
        self.database = self.directory / 'team.sqlite3'
        self.target = self.directory / 'lane-a.json'
        official_target = self.directory / 'official.json'
        for path, name, project in ((official_target, 'competition', self.official), (self.target, 'lane-a', self.project)):
            (project / '.kaizen/config.sh').touch(exist_ok=True)
            path.write_text(json.dumps(dict(environment=name, project=str(project), plugin_root=str(ROOT),
                    knowledge_dir=str(self.directory / ('knowledge-' + name)), resources=['host:' + name],
                    enabled=True, confirmed_rules=True, confirmed_recovery_drill=True)))
        db = connect(self.database)
        register(db, self.database, 'competition', official_target, 'fixture official')
        register(db, self.database, 'lane-a', self.target, 'fixture sandbox')
        db.execute("INSERT INTO sandbox_reservations VALUES ('lane-a','worker','token','sync','now')")
        db.commit()
        db.close()
        baseline = self.project / '.kaizen/baseline' / self.old
        baseline.mkdir(parents=True)
        (baseline / 'old-sample.json').write_text('{"old":true}\n')

    def git(self, project, *args):
        return subprocess.check_output(['git', '-C', str(project), *args], text=True, stderr=subprocess.PIPE)

    def write_proof(self):
        self.record_path.write_text(json.dumps(self.data))
        (self.record_path.parent / 'manifest.json').write_text(json.dumps(self.data['manifest']))
        (self.record_path.parent / 'decision.json').write_text(json.dumps(self.data['ruleDecision']))
        for sample in self.record_path.parent.glob('bench-*.json'):
            sample.unlink()
        for index, sample in enumerate(self.data['samples']):
            (self.record_path.parent / ('bench-' + str(index) + '.json')).write_text(json.dumps(sample))

    def run_sync(self, *args, environment='lane-a', token='token'):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/team/target.py'), '--db', str(self.database),
                '--config', str(self.target), '--environment', environment, '--agent', 'worker', '--token', token,
                'stable-sync', *(args or ('--record', str(self.record_path)))],
                env=self.env, capture_output=True, text=True)

    def state(self):
        return dict(line.split('=', 1) for line in (self.project / '.kaizen/state.env').read_text().splitlines() if '=' in line)

    def test_real_fake_remote_sync_retires_baseline_and_preserves_official(self):
        before = {file: file.read_bytes() for file in self.official.rglob('*') if file.is_file() and '.git' not in file.parts}
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.schema.read_text(), 'adopted schema\n')
        self.assertEqual(self.state()['STABLE_REV'], self.new)
        self.assertEqual(self.state()['DEPLOYED_REV'], self.new)
        self.assertEqual(self.git(self.project, 'rev-parse', 'main').strip(), self.new)
        self.assertFalse((self.project / '.kaizen/stable-sync-pending.json').exists())
        self.assertFalse((self.project / '.kaizen/baseline' / self.new).exists())
        self.assertFalse((self.project / '.kaizen/baseline' / self.old).exists())
        self.assertTrue(list((self.project / '.kaizen/baseline').glob(self.old + '.retired-sync-*')))
        self.assertTrue(all(file.read_bytes() == data for file, data in before.items()))
        # Same adopted SHA only verifies; it does not throw away a newly taken baseline.
        base = self.project / '.kaizen/baseline' / self.new
        base.mkdir(); (base / 'fresh.json').write_text('{"fresh":true}')
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertTrue((base / 'fresh.json').exists())

    def test_failure_rolls_back_and_uncertain_failure_remains_pending(self):
        (self.remote / 'app/fail-initialize').touch()
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        pending = self.project / '.kaizen/stable-sync-pending.json'
        self.assertTrue(pending.exists())
        self.assertEqual(json.loads(pending.read_text())['status'], 'recovery-pending')
        blocked = subprocess.run(['bash', str(ROOT / 'scripts/status.sh')], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('sync is pending', blocked.stderr)
        (self.remote / 'app/fail-initialize').unlink()
        result = self.run_sync('--rollback')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(pending.exists())
        self.assertEqual(self.schema.read_text(), 'original schema\n')
        self.assertEqual(self.state()['STABLE_REV'], self.old)
        self.assertEqual(self.state()['DEPLOYED_REV'], self.old)

    def test_deployment_failure_restores_previous_stable_automatically(self):
        # The build command fails only for the new schema, so the old version can recover.
        config = self.project / '.kaizen/config.sh'
        with config.open('a') as handle:
            handle.write("\nBUILD_CMD=\"! grep -q adopted webapp/app/schema\"\n")
        # Configuration changes need an honest recapture and fresh registration first.
        capture = subprocess.run(['bash', str(ROOT/'scripts/stable.sh'), 'capture'], env=self.env, capture_output=True, text=True)
        self.assertEqual(capture.returncode, 0, capture.stderr)
        db=connect(self.database); db.execute('DELETE FROM sandbox_reservations'); db.commit()
        register(db,self.database,'lane-a',self.target,'changed fixture build check')
        db.execute("INSERT INTO sandbox_reservations VALUES ('lane-a','worker','token','sync','now')"); db.commit(); db.close()
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.schema.read_text(), 'original schema\n')
        self.assertEqual(self.state()['STABLE_REV'], self.old)
        self.assertFalse((self.project / '.kaizen/stable-sync-pending.json').exists())
        history = next((self.project / '.kaizen/stable-syncs').glob('*/sync.json'))
        self.assertEqual(json.loads(history.read_text())['status'], 'rolled-back')

    def test_invalid_proof_wrong_owner_and_busy_state_do_not_deploy(self):
        self.assertNotEqual(self.run_sync(token='stale').returncode, 0)
        self.data['samples'][0]['pass'] = False; self.write_proof()
        self.assertNotEqual(self.run_sync().returncode, 0)
        self.data['samples'][0]['pass'] = True; self.write_proof()
        (self.record_path.parent / 'decision.json').write_text('{}')
        self.assertNotEqual(self.run_sync().returncode, 0)
        self.write_proof()
        with (self.project / '.kaizen/state.env').open('a') as handle:
            handle.write('CURRENT_EXPERIMENT=unfinished\n')
        self.assertNotEqual(self.run_sync().returncode, 0)
        self.assertEqual(self.state()['STABLE_REV'], self.old)
        self.assertEqual(self.schema.read_text(), 'original schema\n')

    def test_non_fast_forward_and_outside_record_are_refused(self):
        (self.project / 'app/local-only').write_text('divergent sandbox\n')
        self.git(self.project, 'add', '.')
        self.git(self.project, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'local-only')
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fast-forward', result.stderr)
        with self.assertRaisesRegex(ValueError, 'registered competition'):
            sync_proof(self.official, self.project / 'record.json', self.project)
        self.assertEqual(self.state()['STABLE_REV'], self.old)

    def test_metadata_repin_allowed_but_newer_deployable_content_needs_its_record(self):
        (self.official / 'README.md').write_text('metadata after adoption\n')
        self.git(self.official, 'add', '.')
        self.git(self.official, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'metadata')
        metadata = self.git(self.official, 'rev-parse', 'main').strip()
        (self.official / '.kaizen/state.env').write_text('STABLE_REV=' + metadata + '\n')
        self.git(self.project, 'fetch', '-q', str(self.official), 'main')
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state()['STABLE_REV'], metadata)
        (self.official / 'app/schema').write_text('newer unrelated adoption\n')
        self.git(self.official, 'add', '.')
        self.git(self.official, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'newer source')
        newer = self.git(self.official, 'rev-parse', 'main').strip()
        (self.official / '.kaizen/state.env').write_text('STABLE_REV=' + newer + '\n')
        self.git(self.project, 'fetch', '-q', str(self.official), 'main')
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('newer deployable content', result.stderr)
        self.assertEqual(self.state()['STABLE_REV'], metadata)
        self.assertEqual(self.schema.read_text(), 'adopted schema\n')


if __name__ == '__main__':
    unittest.main()
