"""Regression: fixture identities must never reach the invoking repository."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _git_test_env

ROOT = Path(__file__).resolve().parents[1]


class GitEnvironmentTests(unittest.TestCase):
    def git(self, project, *args, env=None):
        return subprocess.check_output(['git', '-C', str(project), *args], env=env,
                                       text=True, stderr=subprocess.PIPE).strip()

    def test_fixture_setup_preserves_outer_repository_under_inherited_git_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary) / 'outer'
            outer.mkdir()
            self.git(outer, 'init', '-q')
            self.git(outer, 'config', 'user.name', 'outer-owner')
            self.git(outer, 'config', 'user.email', 'owner@example.invalid')
            original = (outer / '.git/config').read_bytes()
            cases = [
                {'GIT_DIR': str(outer / '.git'), 'GIT_WORK_TREE': str(outer)},
                {'GIT_CONFIG': str(outer / '.git/config')},
                {'GIT_COMMON_DIR': str(outer / '.git')},
                {'GIT_AUTHOR_NAME': 'injected-author', 'GIT_AUTHOR_EMAIL': 'injected@example.invalid',
                 'GIT_COMMITTER_NAME': 'injected-committer', 'GIT_COMMITTER_EMAIL': 'injected@example.invalid'},
                {'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'user.name',
                 'GIT_CONFIG_VALUE_0': 'injected', 'GIT_CONFIG_KEY_1': 'user.email',
                 'GIT_CONFIG_VALUE_1': 'injected@example.invalid'},
            ]
            worker = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_source_proof import SourceProofTests
case = SourceProofTests()
try:
    case.setUp()
    assert case.git('config', '--local', 'user.name') == 'fixture'
    assert case.git('config', 'user.name') == 'fixture'
    assert case.git('log', '-1', '--format=%an|%cn') == 'fixture|fixture'
    assert Path(case.git('rev-parse', '--show-toplevel')).resolve() == case.project.resolve()
finally:
    case.doCleanups()
'''
            for inherited in cases:
                with self.subTest(variables=sorted(inherited)):
                    result = subprocess.run([sys.executable, '-c', worker, str(ROOT / 'tests')],
                                            env={**os.environ, **inherited}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((outer / '.git/config').read_bytes(), original)
                    self.assertEqual(self.git(outer, 'config', 'user.name'), 'outer-owner')
                    self.assertFalse((outer / '.git/refs/heads/main').exists())

    def test_shell_runner_clears_exported_git_configuration(self):
        # Run the runner's exact preamble only; no fake-remote operations needed.
        preamble = (ROOT / 'tests/run.sh').read_text().split('T=$(mktemp', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary)
            self.git(outer, 'init', '-q')
            self.git(outer, 'config', 'user.name', 'outer-owner')
            original = (outer / '.git/config').read_bytes()
            script = preamble + '\nif compgen -e | grep -q "^GIT_"; then exit 91; fi\n'
            result = subprocess.run(['bash', '-c', script, str(ROOT / 'tests/run.sh')],
                                    env={**os.environ, 'GIT_DIR': str(outer / '.git'),
                                         'GIT_CONFIG': str(outer / '.git/config')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((outer / '.git/config').read_bytes(), original)
