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

    def check(self, code, timeout=5):
        r = subprocess.run([sys.executable,str(ROOT/'scripts/check.py'),'--project',str(self.project),
            '--label','regression','--timeout',str(timeout),'--',sys.executable,'-c',code],capture_output=True,text=True)
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


if __name__ == '__main__':
    unittest.main()
