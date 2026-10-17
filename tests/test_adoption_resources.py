"""Adoption must retain the resources that produced its candidate measurements."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import test_initialize

ROOT = Path(__file__).resolve().parents[1]


class AdoptionResourceTests(unittest.TestCase):
    def setUp(self):
        test_initialize.InitializeTarget.setUp(self)
        self.probed = self._testMethodName != 'test_empty_probe_remains_compatible'
        config = self.project / '.kaizen/config.sh'
        with config.open('a') as handle:
            handle.write('''
BENCH_MODE=ssh
BENCH_HOST=bench
RESOURCE_PATHS=sql
RESOURCE_FINGERPRINT_CMD='test ! -f fail-probe && cat database'
bench_command() { printf '%s\\n' 'cp "$KAIZEN_FAKE_REMOTE/app/webapp/app/schema" "$KAIZEN_FAKE_REMOTE/app/database"; cat result'; }
parse_bench() { cat "$1"; }
MAX_BENCH_PER_EXP=8
PROBLEM=test-adoption-resources
RETRO_BLOCK_AFTER=1000
''')
            if not self.probed:
                handle.write("RESOURCE_FINGERPRINT_CMD=''\nRECOVERY_CMD=''\n")
        knowledge = self.directory / 'knowledge'
        shutil.copytree(ROOT / 'knowledge', knowledge)
        self.env['KAIZEN_KNOWLEDGE_DIR'] = str(knowledge)
        (self.remote / 'bench').mkdir()
        self.result = self.remote / 'bench/result'
        self.run_script('stable', 'initialize', 'main')
        self.old = self.git('rev-parse', 'main').strip()
        self.bench('baseline-1', 1000)
        self.bench('baseline-2', 1100)
        self.run_script('experiment', 'new', 'schema-candidate')
        self.experiment = self.project / '.kaizen/experiments/001-schema-candidate'
        manifest_path = self.experiment / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest.update(hypothesis='candidate schema improves the measured path', expectedEffect='higher score',
                        observations=[dict(summary='fixture schema cost', artifact='fixture-observation.txt')],
                        review='human', humanQuestion='Adopt the schema tradeoff?')
        manifest_path.write_text(json.dumps(manifest))
        (self.project / 'app/schema').write_text('candidate schema\n')
        self.git('add', 'app/schema')
        self.git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'candidate schema')
        self.candidate = self.git('rev-parse', 'HEAD').strip()
        self.run_script('deploy', self.candidate)
        self.bench('candidate-1', 3000)
        self.bench('candidate-2', 3100)
        self.run_script('evaluate')
        decision = json.loads((self.experiment / 'decision.json').read_text())
        self.assertEqual(decision['decision'], 'promote')
        self.samples_before = {file.name: file.read_bytes() for file in self.experiment.glob('bench-candidate*.json')}
        self.run_script('recover')
        if not self.probed:
            # A fake external restore is unobservable when no resource probe is configured.
            self.schema.write_text('original schema\n')
        self.assertEqual(self.schema.read_text(), 'original schema\n')
        self.run_script('deploy', self.candidate)
        self.assertEqual(self.schema.read_text(), 'original schema\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], text=True, stderr=subprocess.PIPE)

    def run_script(self, action, *arguments, expect_success=True):
        result = subprocess.run(['bash', str(ROOT / 'scripts' / (action + '.sh')), *arguments],
                                cwd=self.project, env=self.env, capture_output=True, text=True)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def bench(self, label, score):
        self.result.write_text('true ' + str(score) + ' none\n')
        self.run_script('bench', label)

    def record(self):
        return self.run_script('experiment', 'record', '--human-decision', 'fixture: actual approval',
                               'approve the measured candidate', expect_success=False)

    def assert_not_promoted(self, result):
        self.assertNotEqual(result.returncode, 0, 'old schema was accepted as the measured candidate: ' + result.stdout)
        self.assertEqual(self.git('rev-parse', 'main').strip(), self.old)
        state = (self.project / '.kaizen/state.env').read_text()
        self.assertIn('STABLE_REV=' + self.old, state)
        self.assertIn('CURRENT_EXPERIMENT=001-schema-candidate', state)
        self.assertFalse((self.experiment / 'record.json').exists())
        self.assertTrue(all((self.experiment / name).read_bytes() == data for name, data in self.samples_before.items()))

    def test_human_wait_restore_and_code_redeploy_cannot_adopt_old_resources(self):
        result = self.record()
        self.assert_not_promoted(result)
        self.assertIn('measured candidate resources', result.stderr)
        self.assertEqual(self.schema.read_text(), 'original schema\n')

    def test_additional_initializing_benchmark_keeps_old_samples_and_allows_adoption(self):
        self.bench('candidate-3', 3200)
        self.assertEqual(self.schema.read_text(), 'candidate schema\n')
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'main').strip(), self.candidate)
        bundle = json.loads((self.project / '.kaizen/stable-bundle.json').read_text())
        sample = json.loads((self.experiment / 'bench-candidate-1.json').read_text())
        self.assertEqual(bundle['resourceFingerprints'], sample['resourceFingerprints'])
        self.assertTrue(all((self.experiment / name).read_bytes() == data for name, data in self.samples_before.items()))

    def test_probe_failure_leaves_main_stable_and_open_experiment(self):
        (self.remote / 'app/fail-probe').touch()
        result = self.record()
        self.assert_not_promoted(result)
        self.assertIn('resource probe', result.stderr)

    def test_empty_probe_remains_compatible(self):
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'main').strip(), self.candidate)
        self.assertEqual(json.loads((self.project / '.kaizen/stable-bundle.json').read_text())['resourceFingerprints'], {})


if __name__ == '__main__':
    unittest.main()
