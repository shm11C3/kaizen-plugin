"""Initial deployment must establish resource identity before recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InitializeTarget(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.project = self.directory / 'project'
        (self.project / 'app').mkdir(parents=True)
        (self.project / '.kaizen').mkdir()
        (self.project / 'app/schema').write_text('original schema\n')
        (self.project / '.gitignore').write_text('.kaizen/\n')
        self.remote = self.directory / 'remote'
        (self.remote / 'app').mkdir(parents=True)
        self.schema = self.remote / 'app/database'
        self.schema.write_text('unrelated old schema\n')
        (self.project / '.kaizen/config.sh').write_text('''
APP_HOST=app
REMOTE_APP_DIR=webapp
LOCAL_SYNC_PATHS=app
BUILD_CMD=true
RESTART_CMD=true
HEALTH_CMD=true
BENCH_MODE=manual
RESOURCE_HOSTS=app
RESOURCE_FINGERPRINT_CMD='cat database'
RECOVERY_CMD='test ! -f fail-initialize && cp webapp/app/schema database'
''')
        binary = self.directory / 'bin'
        binary.mkdir()
        for name, contents in {
            'sudo': '#!/bin/sh\nexec "$@"\n',
            'md5sum': '#!' + sys.executable + '\nimport hashlib,sys\nfor p in sys.argv[1:]: print(hashlib.md5(open(p,"rb").read()).hexdigest()+"  "+p)\n',
        }.items():
            path = binary / name
            path.write_text(contents)
            path.chmod(0o755)
        self.env = dict(os.environ, KAIZEN_PROJECT=str(self.project), KAIZEN_PLUGIN_ROOT=str(ROOT),
                        KAIZEN_FAKE_REMOTE=str(self.remote), PATH=str(binary)+os.pathsep+os.environ['PATH'])
        self.env.pop('KAIZEN_TEAM_MODE', None)
        for command in [['git', 'init', '-q', '-b', 'main'], ['git', 'config', 'user.name', 'fixture'],
                        ['git', 'config', 'user.email', 'fixture@example.test'], ['git', 'add', '.'],
                        ['git', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'initial']]:
            subprocess.run(command, cwd=self.project, check=True, capture_output=True, env=self.env)

    def initialize(self):
        return subprocess.run(['bash', str(ROOT/'scripts/stable.sh'), 'initialize', 'main'],
                              cwd=self.project, env=self.env, capture_output=True, text=True)

    def test_initializes_before_capture_and_refuses_reentry(self):
        result = self.initialize()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.schema.read_text(), 'original schema\n')
        bundle = self.project/'.kaizen/stable-bundle.json'
        self.assertTrue(json.loads(bundle.read_text())['resourceFingerprints'])
        saved = bundle.read_bytes()
        self.schema.write_text('preserve current state\n')
        result = self.initialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already initialized', result.stderr)
        self.assertEqual(self.schema.read_text(), 'preserve current state\n')
        self.assertEqual(bundle.read_bytes(), saved)

    def test_failed_resource_initialization_never_captures_bundle(self):
        (self.remote/'app/fail-initialize').touch()
        result = self.initialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project/'.kaizen/stable-bundle.json').exists())
        self.assertEqual(self.schema.read_text(), 'unrelated old schema\n')
        self.assertNotEqual(self.initialize().returncode, 0)


if __name__ == '__main__':
    unittest.main()
