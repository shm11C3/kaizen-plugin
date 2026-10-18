"""Configured existing checks run on the composed SHA before target deployment."""
import json
from pathlib import Path
import sys

from test_integrator import IntegratorFixture


class IntegratorChecks(IntegratorFixture):
    def configure(self, checks):
        path = self.state / 'integrator.json'
        settings = json.loads(path.read_text())
        settings.update(review='none', checks=checks)
        path.write_text(json.dumps(settings))

    def test_configured_suite_and_advisory_lint_run_before_deployment(self):
        self.configure([
            {'label': 'test', 'cwd': 'go', 'command': [sys.executable, '-c',
             'from pathlib import Path; assert Path("score").read_text().strip() == "2000"']},
            {'label': 'format', 'cwd': 'go', 'command': [sys.executable, '-c',
             'print("formatting suggestion"); raise SystemExit(1)'], 'advisory': True},
            {'label': 'lint', 'cwd': 'go', 'command': [sys.executable, '-c', 'print("lint complete")']},
        ])
        task = self.submit('Checked candidate', 'worker/checked', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        self.assertEqual(self.tasks()[task]['status'], 'ACCEPTED')
        events = self.ledger(task)
        checks = [event for event in events if event['event'] == 'checks']
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['status'], 'needs_review')
        self.assertLess(events.index(checks[0]), next(i for i, row in enumerate(events) if row['event'] == 'deploy'))
        receipt = json.loads(Path(checks[0]['record']).read_text())
        self.assertEqual(receipt['revision'], self.sha(self.project, 'main'))
        self.assertEqual(len(receipt['checks']), 3)
        advisory = next(item for item in receipt['checks'] if item['label'] == 'format')
        self.assertEqual(advisory['status'], 'failed')
        self.assertTrue(advisory['declaredAdvisory'])
        self.assertEqual(advisory['nativeResult']['sourceBefore']['revision'], receipt['revision'])
        self.assertFalse(self.claude_log.exists(), 'native checks do not require a model call')

    def test_failed_suite_preserves_evidence_and_hold_without_deploying_candidate(self):
        self.configure([
            {'label': 'test', 'cwd': 'go', 'command': [sys.executable, '-c',
             'print("reproducible test failure"); raise SystemExit(1)']},
            {'label': 'lint', 'cwd': 'go', 'command': [sys.executable, '-c', 'print("lint still ran")']},
        ])
        stable = self.sha(self.project, 'main')
        task = self.submit('Broken candidate', 'worker/check-fails', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        self.assertEqual(self.tasks()[task]['status'], 'NEEDS_MEASUREMENT')
        events = self.ledger(task)
        self.assertNotIn('deploy', [row['event'] for row in events])
        self.assertNotIn('bench', [row['event'] for row in events])
        checks = next(row for row in events if row['event'] == 'checks')
        self.assertEqual(checks['status'], 'failed')
        receipt = json.loads(Path(checks['record']).read_text())
        self.assertEqual(len(receipt['checks']), 2)
        self.assertEqual(receipt['checks'][1]['status'], 'passed')
        self.assertIn('reproducible test failure', Path(receipt['checks'][0]['log']).read_text())
        holds = self.team('status')['quality_holds']
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]['category'], 'correctness')
        self.assertEqual(holds[0]['evidence'], checks['record'])
        self.assertEqual(self.state_env()['CURRENT_EXPERIMENT'], '')
        self.assertEqual(self.state_env()['DEPLOYED_REV'], stable)
        self.assertEqual(self.state_env()['STABLE_REV'], stable)
        self.assertIsNone(self.team('status')['environment'])

    def test_unconfigured_suite_is_explicitly_unmeasured(self):
        self.configure([])
        task = self.submit('No registered checks', 'worker/no-checks', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        event = next(row for row in self.ledger(task) if row['event'] == 'checks')
        self.assertEqual(event['status'], 'not_configured')
        self.assertEqual(event['checks'], [])

    def test_advisory_check_cannot_rewrite_the_tested_source(self):
        self.configure([{'label': 'format', 'cwd': 'go', 'advisory': True,
                         'command': [sys.executable, '-c',
                                     'from pathlib import Path; Path("score").write_text("3000\\n")']}])
        stable = self.sha(self.project, 'main')
        task = self.submit('Immutable checks', 'worker/immutable-check', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        self.assertEqual(self.tasks()[task]['status'], 'NEEDS_MEASUREMENT')
        event = next(row for row in self.ledger(task) if row['event'] == 'checks')
        self.assertEqual(event['status'], 'failed')
        receipt = json.loads(Path(event['record']).read_text())['checks'][0]
        self.assertTrue(receipt['declaredAdvisory'])
        self.assertFalse(receipt['sourceIntegrityPassed'])
        self.assertEqual(self.team('status')['quality_holds'][0]['category'], 'conditions')
        self.assertEqual(self.state_env()['DEPLOYED_REV'], stable)
        self.assertNotIn('deploy', [row['event'] for row in self.ledger(task)])

    def test_unclassified_warning_returns_to_ai_instead_of_auto_deploying(self):
        output = '\n'.join(json.dumps(item) for item in [
            {'reason': 'compiler-message', 'message': {'level': 'warning',
             'message': 'possible correctness defect', 'code': {'code': 'clippy::correctness'}, 'spans': []}},
            {'reason': 'build-finished', 'success': True},
        ])
        self.configure([{'label': 'clippy', 'diagnostics': 'cargo',
                         'command': [sys.executable, '-c', 'print(' + repr(output) + ')']}])
        task = self.submit('Unclassified warning', 'worker/warning-check', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        self.assertEqual(self.tasks()[task]['status'], 'NEEDS_MEASUREMENT')
        self.assertEqual(self.team('status')['quality_holds'][0]['category'], 'warning')
        event = next(row for row in self.ledger(task) if row['event'] == 'checks')
        self.assertEqual(event['status'], 'needs_review')
        self.assertNotIn('deploy', [row['event'] for row in self.ledger(task)])

    def test_compiler_error_cannot_be_waived_by_advisory_configuration(self):
        output = '\n'.join(json.dumps(item) for item in [
            {'reason': 'compiler-message', 'message': {'level': 'error',
             'message': 'does not compile', 'code': None, 'spans': []}},
            {'reason': 'build-finished', 'success': False},
        ])
        self.configure([{'label': 'clippy', 'diagnostics': 'cargo', 'advisory': True,
                         'command': [sys.executable, '-c', 'print(' + repr(output) + '); raise SystemExit(1)']}])
        task = self.submit('Compiler failure', 'worker/compiler-check', {'go/score': '2000\n'})
        self.assertTrue(self.once()['processed'])
        self.assertEqual(self.tasks()[task]['status'], 'NEEDS_MEASUREMENT')
        self.assertEqual(self.team('status')['quality_holds'][0]['category'], 'correctness')
        self.assertNotIn('deploy', [row['event'] for row in self.ledger(task)])
