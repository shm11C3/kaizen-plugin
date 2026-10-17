"""Portal-counter integration tests against an isolated fake remote, no servers."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measurement', ROOT/'scripts/measurement.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PortalRequestCounts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root/'project'
        self.project.mkdir()
        (self.project/'app').mkdir()
        (self.project/'app/source.txt').write_text('stable')
        (self.project/'.kaizen').mkdir()
        self.config = self.project/'.kaizen/config.sh'
        self.original_config = '''
APP_HOST=isu1
APP_HOSTS=isu1
REMOTE_APP_DIR=webapp
LOCAL_SYNC_PATHS=app
BUILD_CMD=true
RESTART_CMD=true
HEALTH_CMD=true
BENCH_MODE=manual
REQUEST_COUNT_CMD='cat request-counter'
NGINX_HOST=isu1
'''
        self.config.write_text(self.original_config)
        self.remote = self.root/'remote'
        (self.remote/'isu1').mkdir(parents=True)
        self.counter = self.remote/'isu1/request-counter'
        self.counter.write_text('100\n')
        binary = self.root/'bin'
        binary.mkdir()
        shim = binary/'md5sum'
        shim.write_text('#!'+sys.executable+'\nimport hashlib,sys\n'
                        'for path in sys.argv[1:]:\n'
                        ' print(hashlib.md5(open(path,"rb").read()).hexdigest()+"  "+path)\n')
        shim.chmod(0o755)
        sudo = binary/'sudo'
        sudo.write_text('#!/bin/sh\nexec "$@"\n')
        sudo.chmod(0o755)
        self.env = dict(os.environ, KAIZEN_PROJECT=str(self.project), KAIZEN_PLUGIN_ROOT=str(ROOT),
                        KAIZEN_FAKE_REMOTE=str(self.remote), PATH=str(binary)+os.pathsep+os.environ['PATH'])
        self.env.pop('KAIZEN_TEAM_MODE', None)
        for command in [['git','init','-q','-b','main'], ['git','config','user.name','fixture'],
                        ['git','config','user.email','fixture@example.test'], ['git','add','app'],
                        ['git','-c','commit.gpgsign=false','commit','-qm','stable']]:
            subprocess.run(command,cwd=self.project,env=self.env,check=True,capture_output=True)
        revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.project,text=True).strip()
        (self.project/'.kaizen/state.env').write_text('STABLE_REV='+revision+'\n')
        self.run_script('deploy.sh','main')
        self.run_script('stable.sh','capture')

    def run_script(self, name, *args, success=True):
        process = subprocess.run(['bash',str(ROOT/'scripts'/name),*args],cwd=self.project,
                                 env=self.env,capture_output=True,text=True)
        if success:
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        else:
            self.assertNotEqual(process.returncode,0,process.stdout+process.stderr)
        return process

    def result(self, label, *args):
        self.run_script('bench.sh',label,'--result','pass=true score=3000 errors=map[25:1]',*args)
        paths = list((self.project/'.kaizen/baseline').glob('*/bench-*-'+label+'.json'))
        self.assertEqual(len(paths),1)
        return json.loads(paths[0].read_text())

    def test_manual_counter_snapshot_delta_and_explicit_input_provenance(self):
        self.run_script('bench.sh','baseline-auto','--reserve')
        pending = json.loads((self.project/'.kaizen/manual-bench.json').read_text())
        self.assertEqual(pending['requestCountBefore'],100)
        self.assertEqual(pending['requestSource']['method'],'counter-delta')
        self.counter.write_text('137\n')
        automatic = self.result('baseline-auto')
        self.assertEqual(automatic['requests'],37)
        self.assertEqual(automatic['requestSource']['before'],100)
        self.assertEqual(automatic['requestSource']['after'],137)
        self.assertEqual(automatic['requestSource']['host'],'isu1')
        self.assertEqual(automatic['requestSource']['status'],'available')

        self.run_script('bench.sh','baseline-input','--reserve')
        explicit = self.result('baseline-input','--requests','200')
        self.assertEqual(explicit['requests'],200)
        self.assertEqual(explicit['requestSource']['method'],'explicit')
        for rule in ('v2','v3'):
            candidate = dict(explicit,deployedRevision='candidate',score=9000)
            verdict = m.assess([automatic],[candidate],automatic['deployedRevision'],
                               automatic['stableBundleId'],rule=rule)
            self.assertEqual(verdict['decision'],'inconclusive')
            self.assertEqual(verdict['nextAction'],'remeasure')
            self.assertIn('request denominator sources differ',verdict['reason'])
        self.counter.write_text('0\n')
        self.run_script('bench.sh','baseline-zero','--reserve')
        self.counter.write_text('9\n')
        zero = self.result('baseline-zero')
        self.assertEqual(zero['requests'],9)
        self.assertEqual(zero['requestSource']['before'],0)

    def test_method_host_and_parser_changes_refuse_new_runs_and_pending_result(self):
        self.run_script('bench.sh','baseline-pending','--reserve')
        pending = self.project/'.kaizen/manual-bench.json'
        saved = pending.read_bytes()
        for change in ["REQUEST_COUNT_CMD='echo 999'", 'NGINX_HOST=isu2',
                       'parse_bench_requests() { echo 999; }']:
            with self.subTest(change=change):
                self.config.write_text(self.original_config+'\n'+change+'\n')
                failed = self.run_script('bench.sh','baseline-pending','--result',
                                         'pass=true score=9000 errors=none',success=False)
                self.assertIn('target config changed',failed.stderr)
                self.assertEqual(pending.read_bytes(),saved)
                self.assertEqual(list((self.project/'.kaizen/baseline').glob('*/*.json')),[])
        self.config.write_text(self.original_config)
        self.counter.write_text('142\n')
        self.assertEqual(self.result('baseline-pending')['requests'],42)
        for change in ["REQUEST_COUNT_CMD='echo 999'", 'NGINX_HOST=isu2',
                       'parse_bench_requests() { echo 999; }']:
            with self.subTest(before_run=change):
                self.config.write_text(self.original_config+'\n'+change+'\n')
                failed = self.run_script('bench.sh','baseline-new','--reserve',success=False)
                self.assertIn('target config changed',failed.stderr)
                self.assertFalse(pending.exists())

    def test_counter_reset_noisy_output_and_read_failure_remain_unknown(self):
        for label, before, after, status in [
            ('baseline-reset','100\n','4\n','counter-reset'),
            ('baseline-noisy','100\n','12\n34\n','unavailable'),
            ('baseline-missing',None,'150\n','unavailable')]:
            with self.subTest(label=label):
                if before is None:
                    self.counter.unlink()
                else:
                    self.counter.write_text(before)
                self.run_script('bench.sh',label,'--reserve')
                self.counter.write_text(after)
                sample = self.result(label)
                self.assertIsNone(sample['requests'])
                self.assertEqual(sample['requestSource']['status'],status)


if __name__=='__main__':
    unittest.main()
