"""Candidate QA uses the existing check tool on isolated, source-bound worktrees."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))
import candidate_checks as module


class CandidateChecksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        (self.project / 'go').mkdir(parents=True)
        (self.project / 'go/source.txt').write_text('original')
        (self.project / 'other.txt').write_text('unchanged sibling')
        (self.project / '.gitignore').write_text('.kaizen/\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.commit()
        self.state = self.root / 'state'

    def git(self, *arguments):
        return subprocess.check_output(['git', '-C', str(self.project), *arguments],
                                       stderr=subprocess.PIPE, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture source')
        self.candidate = self.git('rev-parse', 'HEAD')

    def check(self, label, code, **settings):
        return dict(label=label, cwd='go', command=[sys.executable, '-c', code], **settings)

    def run_checks(self, checks):
        result = module.run_checks(self.project, self.candidate, checks, self.state)
        self.assertEqual(self.git('worktree', 'list').count('\n'), 0)
        return result

    def test_all_commands_run_and_raw_evidence_is_immutable(self):
        checks = [self.check('first', 'print("first ran")'), self.check('second', 'print("second ran")')]
        receipts = self.run_checks(checks)
        self.assertEqual([r['status'] for r in receipts], ['passed', 'passed'])
        hashes = {}
        for index, receipt in enumerate(receipts):
            self.assertTrue(receipt['sourceIntegrityPassed'])
            self.assertEqual(receipt['nativeResult']['sourceBefore'], receipt['nativeResult']['sourceAfter'])
            self.assertEqual(receipt['nativeResult']['sourceBefore']['revision'], self.candidate)
            self.assertIn(('first', 'second')[index] + ' ran', Path(receipt['log']).read_text())
            self.assertTrue(Path(receipt['record']).is_file())
            native = json.loads(Path(receipt['nativeRecord']).read_text())
            self.assertEqual(native['status'], receipt['nativeResult']['status'])
            for name in ('record', 'nativeRecord', 'log'):
                path = Path(receipt[name])
                hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        again = self.run_checks(checks[:1])
        self.assertNotEqual(again[0]['record'], receipts[0]['record'])
        self.assertTrue(all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in hashes.items()))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_failure_does_not_skip_remaining_commands(self):
        receipts = self.run_checks([self.check('fails', 'print("failure"); raise SystemExit(7)'),
                                    self.check('next', 'print("still ran")')])
        self.assertEqual([r['status'] for r in receipts], ['failed', 'passed'])
        self.assertEqual(receipts[0]['nativeResult']['exitCode'], 7)
        self.assertTrue(receipts[0]['sourceIntegrityPassed'])
        self.assertIn('still ran', Path(receipts[1]['log']).read_text())

    def test_mismatched_sha_and_dirty_source_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'does not match HEAD'):
            module.run_checks(self.project, 'f' * 40, [self.check('test', 'pass')], self.state)
        (self.project / 'go/source.txt').write_text('uncommitted')
        with self.assertRaisesRegex(ValueError, 'clean committed'):
            self.run_checks([self.check('test', 'pass')])

    def test_source_mutation_fails_and_later_checks_use_the_original_candidate(self):
        receipts = self.run_checks([
            self.check('mutates', 'from pathlib import Path; Path("source.txt").write_text("changed")'),
            self.check('next', 'from pathlib import Path; assert Path("source.txt").read_text()=="original"; print("restored")')])
        self.assertEqual([r['status'] for r in receipts], ['failed', 'passed'])
        self.assertFalse(receipts[0]['sourceIntegrityPassed'])
        self.assertTrue(receipts[0]['nativeResult']['sourceChanged'])
        self.assertIn('restored', Path(receipts[1]['log']).read_text())
        self.assertEqual((self.project / 'go/source.txt').read_text(), 'original')

    def test_sibling_mutation_is_detected_without_rewriting_native_result(self):
        receipts = self.run_checks([self.check('sibling',
            'from pathlib import Path; Path("../other.txt").write_text("changed")', advisory=True)])
        self.assertEqual(receipts[0]['status'], 'failed')
        self.assertFalse(receipts[0]['sourceIntegrityPassed'])
        self.assertTrue(receipts[0]['declaredAdvisory'])
        self.assertEqual(receipts[0]['nativeResult']['status'], 'passed')
        self.assertTrue(receipts[0]['nativeResult']['passed'])
        self.assertEqual((self.project / 'other.txt').read_text(), 'unchanged sibling')

    def test_absolute_parent_and_symlink_cwd_escape_are_refused(self):
        for cwd in ('/tmp', '../outside', 'go/../../outside'):
            with self.subTest(cwd=cwd), self.assertRaisesRegex(ValueError, 'inside the project'):
                module.run_checks(self.project, self.candidate,
                                  [dict(label='test', cwd=cwd, command=[sys.executable, '-c', 'pass'])], self.state)
        (self.project / 'escape').symlink_to(self.root, target_is_directory=True)
        self.commit()
        with self.assertRaisesRegex(ValueError, 'project directory'):
            module.run_checks(self.project, self.candidate,
                              [dict(label='test', cwd='escape', command=[sys.executable, '-c', 'pass'])], self.state)

    def test_gofmt_findings_are_retained_as_needs_review(self):
        receipt = self.run_checks([self.check('format', 'print("main.go")', diagnostics='gofmt')])[0]
        self.assertEqual(receipt['status'], 'needs_review')
        self.assertTrue(receipt['sourceIntegrityPassed'])
        self.assertEqual(receipt['nativeResult']['exitCode'], 0)
        self.assertFalse(receipt['nativeResult']['passed'])
        self.assertEqual(receipt['nativeResult']['diagnostics'], [dict(level='format', file='main.go')])

    def test_declared_advisory_failure_keeps_raw_failure(self):
        receipt = self.run_checks([self.check('rust-format', 'raise SystemExit(1)', advisory=True)])[0]
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue(receipt['declaredAdvisory'])
        self.assertTrue(receipt['sourceIntegrityPassed'])
        self.assertEqual(receipt['nativeResult']['status'], 'failed')
        self.assertEqual(receipt['nativeResult']['exitCode'], 1)
        self.assertFalse(receipt['nativeResult']['passed'])

    def test_default_cargo_cache_persists_across_candidate_worktrees(self):
        environment = dict(os.environ)
        environment.pop('CARGO_TARGET_DIR', None)
        environment['GOCACHE'] = 'inherited-go-cache'
        command = 'import json,os; print(json.dumps([os.environ["CARGO_TARGET_DIR"],os.environ["GOCACHE"]]))'
        with mock.patch.dict(os.environ, environment, clear=True):
            first = self.run_checks([self.check('cache', command)])[0]
            (self.project / 'go/source.txt').write_text('new candidate')
            self.commit()
            second = self.run_checks([self.check('cache', command)])[0]
        first_cache = json.loads(Path(first['log']).read_text())
        self.assertEqual(first_cache, json.loads(Path(second['log']).read_text()))
        self.assertEqual(first_cache, [str(self.state.resolve() / 'check-cache/cargo'), 'inherited-go-cache'])
        self.assertFalse(first['cache']['inherited'])

    def test_explicit_cargo_target_directory_is_preserved(self):
        with mock.patch.dict(os.environ, {'CARGO_TARGET_DIR': str(self.root / 'existing-cache')}):
            receipt = self.run_checks([self.check('cache', 'import os; print(os.environ["CARGO_TARGET_DIR"])')])[0]
        self.assertTrue(receipt['cache']['inherited'])
        self.assertEqual(Path(receipt['log']).read_text().strip(), str(self.root / 'existing-cache'))

    def test_launcher_error_retains_raw_output_and_runs_remaining_checks(self):
        with mock.patch.object(module, 'CHECK', self.root / 'missing-check.py'):
            receipts = self.run_checks([self.check('first', 'pass'), self.check('second', 'pass')])
        self.assertEqual([r['status'] for r in receipts], ['failed', 'failed'])
        self.assertTrue(all(r['launcherError'] and r['nativeResult'] is None for r in receipts))
        self.assertTrue(all('missing-check.py' in Path(r['log']).read_text() for r in receipts))


if __name__ == '__main__':
    unittest.main()
