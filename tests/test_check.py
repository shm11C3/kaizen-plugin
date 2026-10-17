import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CheckEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(['git','init','-q',str(self.project)],check=True)
        subprocess.run(['git','-C',str(self.project),'config','user.name','fixture'],check=True)
        subprocess.run(['git','-C',str(self.project),'config','user.email','fixture@example.test'],check=True)
        (self.project/'app.txt').write_text('original')
        subprocess.run(['git','-C',str(self.project),'add','app.txt'],check=True)
        subprocess.run(['git','-C',str(self.project),'-c','commit.gpgsign=false','commit','-qm','initial'],check=True)

    def check(self, code, timeout=5, diagnostics=None):
        r = subprocess.run([sys.executable,str(ROOT/'scripts/check.py'),'--project',str(self.project),
            '--label','regression','--timeout',str(timeout),
            *(['--diagnostics',diagnostics] if diagnostics else []),
            '--',sys.executable,'-c',code],capture_output=True,text=True)
        return r, json.loads(r.stdout)

    def test_actual_failures_and_success_preserve_logs_and_source(self):
        r, d = self.check('print("assertion failed"); raise SystemExit(1)')
        self.assertNotEqual(r.returncode,0); self.assertFalse(d['passed'])
        self.assertIn('assertion failed',Path(d['log']).read_text())
        r, d = self.check('print("passed")')
        self.assertEqual(r.returncode,0); self.assertTrue(d['passed'])
        self.assertEqual(d['sourceBefore'],d['sourceAfter'])
        self.assertTrue(Path(d['record']).is_file())

    def test_timeout_and_source_change_do_not_report_passing_checks(self):
        r, d = self.check('import time; time.sleep(5)',1)
        self.assertNotEqual(r.returncode,0); self.assertTrue(d['timedOut'])
        r, d = self.check('from pathlib import Path; Path("app.txt").write_text("changed")')
        self.assertNotEqual(r.returncode,0); self.assertEqual(d['exitCode'],0)
        self.assertTrue(d['sourceChanged']); self.assertFalse(d['passed'])

    def test_head_change_during_successful_command_invalidates_evidence(self):
        r, d = self.check('import subprocess; subprocess.run(["git","-c","commit.gpgsign=false","commit","--allow-empty","-qm","concurrent HEAD change"],check=True)')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(d['exitCode'], 0)
        self.assertNotEqual(d['sourceBefore']['revision'], d['sourceAfter']['revision'])
        self.assertTrue(d['sourceChanged'])
        self.assertFalse(d['passed'])

    def test_formatter_output_requires_review_even_when_native_exit_is_zero(self):
        r, d = self.check('print("main.go")', diagnostics='gofmt')
        self.assertEqual(r.returncode, 3)
        self.assertTrue(d['processPassed'])
        self.assertFalse(d['passed'])
        self.assertEqual(d['status'], 'needs_review')
        self.assertEqual(d['diagnostics'][0]['file'], 'main.go')
        r, d = self.check('pass', diagnostics='gofmt')
        self.assertEqual(r.returncode, 0)

    def test_cargo_warning_requires_triage_but_is_not_reported_as_command_failure(self):
        messages = [dict(reason='compiler-message', message=dict(level='warning',
                    code=dict(code='clippy::needless_return'), message='unneeded return', spans=[])),
                    dict(reason='build-finished', success=True)]
        code = 'print(' + repr('\n'.join(json.dumps(item) for item in messages)) + ')'
        r, d = self.check(code, diagnostics='cargo')
        self.assertEqual(r.returncode, 3)
        self.assertEqual(d['exitCode'], 0)
        self.assertTrue(d['processPassed'])
        self.assertEqual(d['status'], 'needs_review')
        self.assertEqual(d['diagnostics'][0]['code']['code'], 'clippy::needless_return')

    def test_missing_or_malformed_cargo_evidence_cannot_pass(self):
        for output in ['', '{broken', '{"reason":"build-finished","success":false}',
                       '{"reason":"compiler-message"}\n{"reason":"build-finished","success":true}']:
            with self.subTest(output=output):
                r, d = self.check('print(' + repr(output) + ')', diagnostics='cargo')
                self.assertEqual(r.returncode, 2)
                self.assertFalse(d['diagnosticsComplete'])
                self.assertFalse(d['passed'])

    def test_cargo_error_cannot_be_green_even_with_zero_exit_and_success_marker(self):
        output = '\n'.join(json.dumps(item) for item in [
            dict(reason='compiler-message', message=dict(level='error', message='broken')),
            dict(reason='build-finished', success=True)])
        r, d = self.check('print(' + repr(output) + ')', diagnostics='cargo')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(d['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
